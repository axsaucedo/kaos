"""Unit tests for the short-term store (token budget + rolling summary)."""

import os
import uuid

import pytest

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.stores import Scope, ScopeLevel
from kaos_memory.stores import ShortTermStore, scope_key
from kaos_memory.stores import _summary_table_ddl, _window_table_ddl

SCOPE = Scope(level=ScopeLevel.SESSION, session_id="run-1")


def _fake_summarizer(prior, folded):
    folded_join = " | ".join(c for _, c in folded)
    return f"SUMMARY[{prior[:40]}]+[{folded_join}]"


def _sqlite_store(tmp_path, **cfg):
    path = str(tmp_path / "shortterm.db")
    return ShortTermStore("local", path, ShortTermTierConfig(**cfg), _fake_summarizer)


def test_append_and_recent_ordering(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    store.add(SCOPE, [("user", "first")])
    store.add(SCOPE, [("assistant", "second")])
    store.add(SCOPE, [("user", "third")])
    assert store.active_window(SCOPE) == [
        ("user", "first"),
        ("assistant", "second"),
        ("user", "third"),
    ]


def test_budget_overflow_folds_into_summary_when_enabled(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=8, rolling_summary=True)
    turns = [
        ("user", "hello there this is the first message about cluster setup"),
        ("assistant", "acknowledged the cluster has three kubernetes nodes running"),
        ("user", "tell me about the deployment on port 8080 please now"),
        ("assistant", "the deployment is healthy and exposes port 8080 via gateway"),
    ]
    for role, content in turns:
        store.add(SCOPE, [(role, content)])

    summary, active = store.short_term_context(SCOPE)
    key = scope_key(SCOPE)
    # Overflow was folded into a rolling summary, not dropped.
    assert summary, "expected a rolling summary after overflow"
    # The most recent turn stays verbatim.
    assert active[-1] == (turns[-1][0], turns[-1][1])
    # Folded turns are transient: absorbed into the summary and deleted (no unbounded growth).
    total = store.db.execute(
        "SELECT count(*) FROM short_term_memory_window WHERE scope_key = ?", (key,)
    ).fetchone()[0]
    assert total == len(active)
    folded = store.db.execute(
        "SELECT count(*) FROM short_term_memory_window WHERE scope_key = ? AND pending_summary = 1",
        (key,),
    ).fetchone()[0]
    assert folded == 0


def test_budget_overflow_drops_when_summary_disabled(tmp_path):
    # Default behaviour: a recency window that drops overflow with no model call.
    store = _sqlite_store(tmp_path, token_budget=8)
    turns = [
        ("user", "hello there this is the first message about cluster setup"),
        ("assistant", "acknowledged the cluster has three kubernetes nodes running"),
        ("user", "tell me about the deployment on port 8080 please now"),
    ]
    for role, content in turns:
        store.add(SCOPE, [(role, content)])

    key = scope_key(SCOPE)
    # No summary is produced and no rows linger beyond the active window.
    assert store.summary(SCOPE) == ""
    active = store.active_window(SCOPE)
    assert active[-1] == (turns[-1][0], turns[-1][1])
    total = store.db.execute(
        "SELECT count(*) FROM short_term_memory_window WHERE scope_key = ?", (key,)
    ).fetchone()[0]
    assert total == len(active)


def test_summarize_pending_folds_all_marked_rows_in_one_call(tmp_path):
    # The batching guarantee: every pending row is folded in a SINGLE summariser call.
    call_count = 0
    fold_sizes: list[int] = []

    def counting_summarizer(prior, folded):
        nonlocal call_count
        call_count += 1
        fold_sizes.append(len(folded))
        return "rolled up"

    store = ShortTermStore(
        "local",
        str(tmp_path / "pending.db"),
        ShortTermTierConfig(token_budget=8, rolling_summary=True),
        counting_summarizer,
    )
    key = scope_key(SCOPE)
    for i in range(3):
        store.db.execute(
            "INSERT INTO short_term_memory_window (scope_key, role, content, created_at, pending_summary) "
            "VALUES (?, ?, ?, ?, 1)",
            (key, "user", f"m{i}", 0.0),
        )
    store.db.commit()

    store.fold_pending_into_summary(SCOPE)
    assert call_count == 1
    assert fold_sizes == [3]
    # Pending rows are deleted once absorbed into the summary.
    remaining = store.db.execute(
        "SELECT count(*) FROM short_term_memory_window WHERE scope_key = ?", (key,)
    ).fetchone()[0]
    assert remaining == 0


def test_scheduler_defers_fold_off_the_write_path(tmp_path):
    scheduled = []
    store = ShortTermStore(
        "local",
        str(tmp_path / "sched.db"),
        ShortTermTierConfig(token_budget=8, rolling_summary=True),
        _fake_summarizer,
        scheduler=scheduled.append,
    )
    store.add(SCOPE, [("user", "first long-ish message that seeds the window here")])
    store.add(SCOPE, [("assistant", "second message that pushes the window over the small budget")])
    # The fold was scheduled, not run inline: overflow already left the window, but the
    # summary is not written until the scheduled thunk runs.
    assert store.summary(SCOPE) == ""
    assert scheduled, "expected a deferred fold to be scheduled off the write path"
    for thunk in scheduled:
        thunk()
    assert store.summary(SCOPE) != ""


def test_fold_evicts_down_to_compaction_target_target(tmp_path):
    # Once the window crosses compaction_trigger, eviction drops it toward compaction_target rather than
    # to just-under-budget, so folds fire far less often than once per add (amortised).
    calls = {"n": 0}

    def counting(prior, folded):
        calls["n"] += 1
        return "s"

    store = ShortTermStore(
        "local",
        str(tmp_path / "lw.db"),
        ShortTermTierConfig(
            token_budget=60, compaction_trigger=60, compaction_target=15, rolling_summary=True
        ),
        counting,
    )
    key = scope_key(SCOPE)
    for i in range(30):
        store.add(SCOPE, [("user", f"message number {i} here")])
        # Invariant: the active window is always kept at or below compaction_trigger.
        assert store._window_token_total(store._load_active_window_rows(key)) <= 60
    # Amortisation: dropping to compaction_target means folds fire well under once per add.
    assert calls["n"] < 15, calls["n"]


def test_digest_is_versioned_and_pruned(tmp_path):
    # Each fold appends a new digest version; the retention cap keeps only the last N.
    store = ShortTermStore(
        "local",
        str(tmp_path / "v.db"),
        ShortTermTierConfig(token_budget=8, rolling_summary=True, digest_retention=2),
        lambda prior, folded: f"v-{len(prior)}",
    )
    key = scope_key(SCOPE)

    def fold_once(marker):
        store.db.execute(
            "INSERT INTO short_term_memory_window "
            "(scope_key, role, content, created_at, pending_summary) VALUES (?, ?, ?, ?, 1)",
            (key, "user", marker, 0.0),
        )
        store.db.commit()
        store.fold_pending_into_summary(SCOPE)

    for i in range(4):
        fold_once(f"m{i}")

    rows = store.db.execute(
        "SELECT version FROM medium_term_memory_summaries WHERE scope_key = ? ORDER BY version",
        (key,),
    ).fetchall()
    versions = [r[0] for r in rows]
    # Four folds create versions 1..4 but retention=2 keeps only the last two.
    assert versions == [3, 4]
    # Recall always returns the latest version's text.
    assert store.summary(SCOPE) != ""


def test_add_returns_evicted_turns_for_cascade(tmp_path):
    # add() surfaces the batch that left the window so callers can cascade it to
    # long-term extraction, independent of whether the digest fold is enabled.
    store = _sqlite_store(tmp_path, token_budget=8, compaction_trigger=8, compaction_target=4)
    evicted_total: list[tuple[str, str]] = []
    turns = [
        ("user", "hello there this is the first message about cluster setup"),
        ("assistant", "acknowledged the cluster has three kubernetes nodes running"),
        ("user", "tell me about the deployment on port 8080 please now"),
    ]
    for role, content in turns:
        evicted_total.extend(store.add(SCOPE, [(role, content)]))
    # The oldest turns were evicted and returned in order; the newest stays in the window.
    assert evicted_total, "expected add() to return evicted turns after overflow"
    assert evicted_total[0] == turns[0]
    assert turns[-1] not in evicted_total


def test_add_returns_empty_when_within_budget(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    assert store.add(SCOPE, [("user", "small")]) == []


def test_window_table_is_unlogged_on_postgres_only():
    # The ephemeral window is UNLOGGED on Postgres for RAM-speed writes; SQLite has no
    # such notion. The durable medium-term digest is never UNLOGGED on either backend.
    assert "UNLOGGED" in _window_table_ddl("external", "BIGSERIAL PRIMARY KEY")
    assert "UNLOGGED" not in _window_table_ddl("local", "INTEGER PRIMARY KEY AUTOINCREMENT")
    assert "UNLOGGED" not in _summary_table_ddl("external")
    assert "UNLOGGED" not in _summary_table_ddl("local")


def test_scope_lock_is_noop_on_local(tmp_path):
    # On the embedded SQLite backend the per-scope advisory lock is a no-op that still
    # yields, so operations under it behave normally.
    store = _sqlite_store(tmp_path, token_budget=10_000)
    with store.db.scope_lock(scope_key(SCOPE)):
        store.add(SCOPE, [("user", "still works under the lock")])
    assert store.active_window(SCOPE) == [("user", "still works under the lock")]


def test_hard_event_cap_enforced(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000, hard_event_cap=2)
    for i in range(5):
        store.add(SCOPE, [("user", f"turn number {i}")])
    active = store.active_window(SCOPE)
    # Hard cap bounds the active window even though the token budget is huge.
    assert len(active) <= 2
    assert active[-1] == ("user", "turn number 4")


def test_recent_honours_explicit_smaller_budget(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    for i in range(4):
        store.add(SCOPE, [("user", f"message {i} content here")])
    full = store.active_window(SCOPE)
    trimmed = store.active_window(SCOPE, token_budget=5)
    assert len(trimmed) < len(full)
    assert trimmed[-1] == full[-1]


def test_rolling_summary_disabled_does_not_require_summarizer(tmp_path):
    path = str(tmp_path / "w.db")
    store = ShortTermStore(
        "local", path, ShortTermTierConfig(token_budget=8, rolling_summary=False), summarizer=None
    )
    for i in range(5):
        store.add(SCOPE, [("user", f"a fairly long message number {i} to exceed the budget")])
    # No summary produced, but the window is still bounded by folding.
    assert store.summary(SCOPE) == ""
    assert (
        store._window_token_total(store._load_active_window_rows(scope_key(SCOPE))) <= 8
        or len(store.active_window(SCOPE)) == 1
    )


def test_clear_removes_turns_and_summary(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=8, rolling_summary=True)
    for i in range(4):
        store.add(SCOPE, [("user", f"message {i} with enough tokens to trigger summary folding")])
    assert store.summary(SCOPE) != ""
    store.clear(SCOPE)
    assert store.active_window(SCOPE) == []
    assert store.summary(SCOPE) == ""


def test_sessions_are_isolated_within_the_same_owner(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    a = Scope(level=ScopeLevel.USER, principal="alice", session_id="run-a")
    b = Scope(level=ScopeLevel.USER, principal="alice", session_id="run-b")
    store.add(a, [("user", "alpha")])
    store.add(b, [("user", "beta")])
    assert store.active_window(a) == [("user", "alpha")]
    assert store.active_window(b) == [("user", "beta")]


def test_session_delete_removes_only_that_session(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    first = Scope(level=ScopeLevel.SESSION, session_id="run-a")
    second = Scope(level=ScopeLevel.SESSION, session_id="run-b")
    store.add(first, [("user", "alpha")])
    store.add(second, [("user", "beta")])

    store.delete(first)

    assert store.active_window(first) == []
    assert store.active_window(second) == [("user", "beta")]


def test_owner_delete_removes_all_sessions_under_exact_prefix(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    alice_a = Scope(level=ScopeLevel.USER, principal="alice", session_id="run-a")
    alice_b = Scope(level=ScopeLevel.USER, principal="alice", session_id="run-b")
    alicia = Scope(level=ScopeLevel.USER, principal="alicia", session_id="run-c")
    store.add(alice_a, [("user", "alpha")])
    store.add(alice_b, [("user", "beta")])
    store.add(alicia, [("user", "keep")])

    store.delete(Scope(level=ScopeLevel.USER, principal="alice"))

    assert store.active_window(alice_a) == []
    assert store.active_window(alice_b) == []
    assert store.active_window(alicia) == [("user", "keep")]


def test_group_delete_removes_all_group_sessions(tmp_path):
    path = str(tmp_path / "group.db")
    store = ShortTermStore(
        "local",
        path,
        ShortTermTierConfig(token_budget=10_000),
        _fake_summarizer,
        group="team-a",
    )
    first = Scope(level=ScopeLevel.GROUP, session_id="run-a")
    second = Scope(level=ScopeLevel.GROUP, session_id="run-b")
    store.add(first, [("user", "alpha")])
    store.add(second, [("user", "beta")])

    store.delete(Scope(level=ScopeLevel.GROUP))

    assert store.active_window(first) == []
    assert store.active_window(second) == []


def test_conversational_store_fails_without_session(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    scope = Scope(level=ScopeLevel.USER, principal="alice")

    with pytest.raises(ValueError, match="requires session_id"):
        store.add(scope, [("user", "must not be shared")])


@pytest.mark.pgvector
def test_postgres_budget_overflow_summarizes(pgvector_dsn):
    store = ShortTermStore(
        "external",
        pgvector_dsn,
        ShortTermTierConfig(token_budget=8, rolling_summary=True),
        _fake_summarizer,
    )
    scope = Scope(level=ScopeLevel.SESSION, session_id="pg-" + uuid.uuid4().hex[:8])
    for i in range(4):
        store.add(
            scope, [("user", f"a reasonably long postgres turn number {i} about deployments")]
        )
    summary, active = store.short_term_context(scope)
    assert summary
    assert active
    store.clear(scope)
    store.close()
