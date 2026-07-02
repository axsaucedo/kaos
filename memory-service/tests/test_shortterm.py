"""Unit tests for the short-term store (token budget + rolling summary)."""

import os
import uuid

import pytest

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.stores import Scope, ScopeLevel
from kaos_memory.stores import ShortTermStore, scope_key

SCOPE = Scope(level=ScopeLevel.SESSION, session_id="run-1")


def _fake_summarizer(prior, folded):
    folded_join = " | ".join(c for _, c in folded)
    return f"SUMMARY[{prior[:40]}]+[{folded_join}]"


def _sqlite_store(tmp_path, **cfg):
    path = str(tmp_path / "shortterm.db")
    return ShortTermStore("local", path, ShortTermTierConfig(**cfg), _fake_summarizer)


def test_append_and_recent_ordering(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    store.add(SCOPE, "user", "first")
    store.add(SCOPE, "assistant", "second")
    store.add(SCOPE, "user", "third")
    assert store.recent(SCOPE) == [("user", "first"), ("assistant", "second"), ("user", "third")]


def test_budget_overflow_folds_into_summary_when_enabled(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=8, rolling_summary=True)
    turns = [
        ("user", "hello there this is the first message about cluster setup"),
        ("assistant", "acknowledged the cluster has three kubernetes nodes running"),
        ("user", "tell me about the deployment on port 8080 please now"),
        ("assistant", "the deployment is healthy and exposes port 8080 via gateway"),
    ]
    for role, content in turns:
        store.add(SCOPE, role, content)

    summary, active = store.context(SCOPE)
    key = scope_key(SCOPE)
    # Overflow was folded into a rolling summary, not dropped.
    assert summary, "expected a rolling summary after overflow"
    # The most recent turn stays verbatim.
    assert active[-1] == (turns[-1][0], turns[-1][1])
    # Folded turns are transient: absorbed into the summary and deleted (no unbounded growth).
    total = store.db.execute(
        "SELECT count(*) FROM short_term_turns WHERE scope_key = ?", (key,)
    ).fetchone()[0]
    assert total == len(active)
    folded = store.db.execute(
        "SELECT count(*) FROM short_term_turns WHERE scope_key = ? AND folded = 1", (key,)
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
        store.add(SCOPE, role, content)

    key = scope_key(SCOPE)
    # No summary is produced and no rows linger beyond the active window.
    assert store.summary(SCOPE) == ""
    active = store.recent(SCOPE)
    assert active[-1] == (turns[-1][0], turns[-1][1])
    total = store.db.execute(
        "SELECT count(*) FROM short_term_turns WHERE scope_key = ?", (key,)
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
            "INSERT INTO short_term_turns (scope_key, role, content, created_at, folded) "
            "VALUES (?, ?, ?, ?, 1)",
            (key, "user", f"m{i}", 0.0),
        )
    store.db.commit()

    store.summarize_pending(SCOPE)
    assert call_count == 1
    assert fold_sizes == [3]
    # Pending rows are deleted once absorbed into the summary.
    remaining = store.db.execute(
        "SELECT count(*) FROM short_term_turns WHERE scope_key = ?", (key,)
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
    store.add(SCOPE, "user", "first long-ish message that seeds the window here")
    store.add(SCOPE, "assistant", "second message that pushes the window over the small budget")
    # The fold was scheduled, not run inline: overflow already left the window, but the
    # summary is not written until the scheduled thunk runs.
    assert store.summary(SCOPE) == ""
    assert scheduled, "expected a deferred fold to be scheduled off the write path"
    for thunk in scheduled:
        thunk()
    assert store.summary(SCOPE) != ""


def test_hard_event_cap_enforced(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000, hard_event_cap=2)
    for i in range(5):
        store.add(SCOPE, "user", f"turn number {i}")
    active = store.recent(SCOPE)
    # Hard cap bounds the active window even though the token budget is huge.
    assert len(active) <= 2
    assert active[-1] == ("user", "turn number 4")


def test_recent_honours_explicit_smaller_budget(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    for i in range(4):
        store.add(SCOPE, "user", f"message {i} content here")
    full = store.recent(SCOPE)
    trimmed = store.recent(SCOPE, token_budget=5)
    assert len(trimmed) < len(full)
    assert trimmed[-1] == full[-1]


def test_rolling_summary_disabled_does_not_require_summarizer(tmp_path):
    path = str(tmp_path / "w.db")
    store = ShortTermStore(
        "local", path, ShortTermTierConfig(token_budget=8, rolling_summary=False), summarizer=None
    )
    for i in range(5):
        store.add(SCOPE, "user", f"a fairly long message number {i} to exceed the budget")
    # No summary produced, but the window is still bounded by folding.
    assert store.summary(SCOPE) == ""
    assert (
        store._active_tokens(store._active(scope_key(SCOPE))) <= 8 or len(store.recent(SCOPE)) == 1
    )


def test_clear_removes_turns_and_summary(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=8, rolling_summary=True)
    for i in range(4):
        store.add(SCOPE, "user", f"message {i} with enough tokens to trigger summary folding")
    assert store.summary(SCOPE) != ""
    store.clear(SCOPE)
    assert store.recent(SCOPE) == []
    assert store.summary(SCOPE) == ""


def test_scopes_are_isolated(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    a = Scope(level=ScopeLevel.SESSION, session_id="run-a")
    b = Scope(level=ScopeLevel.SESSION, session_id="run-b")
    store.add(a, "user", "alpha")
    store.add(b, "user", "beta")
    assert store.recent(a) == [("user", "alpha")]
    assert store.recent(b) == [("user", "beta")]


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
        store.add(scope, "user", f"a reasonably long postgres turn number {i} about deployments")
    summary, active = store.context(scope)
    assert summary
    assert active
    store.clear(scope)
    store.close()
