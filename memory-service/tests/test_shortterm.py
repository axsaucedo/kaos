"""Unit tests for the short-term store (token budget + rolling summary)."""

import os
import uuid

import pytest

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.scope import Scope, ScopeLevel
from kaos_memory.shortterm import ShortTermStore, scope_key

SCOPE = Scope(level=ScopeLevel.SESSION, session_id="run-1")


def _fake_summarizer(prior, folded):
    folded_join = " | ".join(c for _, c in folded)
    return f"SUMMARY[{prior[:40]}]+[{folded_join}]"


def _sqlite_store(tmp_path, **cfg):
    path = str(tmp_path / "shortterm.db")
    return ShortTermStore("local", path, ShortTermTierConfig(**cfg), _fake_summarizer)


def test_append_and_recent_ordering(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    store.append(SCOPE, "user", "first")
    store.append(SCOPE, "assistant", "second")
    store.append(SCOPE, "user", "third")
    assert store.recent(SCOPE) == [("user", "first"), ("assistant", "second"), ("user", "third")]


def test_budget_overflow_summarizes_not_truncates(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=8)
    turns = [
        ("user", "hello there this is the first message about cluster setup"),
        ("assistant", "acknowledged the cluster has three kubernetes nodes running"),
        ("user", "tell me about the deployment on port 8080 please now"),
        ("assistant", "the deployment is healthy and exposes port 8080 via gateway"),
    ]
    for role, content in turns:
        store.append(SCOPE, role, content)

    summary, active = store.context(SCOPE)
    key = scope_key(SCOPE)
    # A rolling summary exists (eviction was by summarization).
    assert summary, "expected a rolling summary after overflow"
    # The most recent turn stays verbatim.
    assert active[-1] == (turns[-1][0], turns[-1][1])
    # Older turns were folded, not deleted: all raw rows are retained.
    total = store.db.execute(
        "SELECT count(*) FROM short_term_turns WHERE scope_key = ?", (key,)
    ).fetchone()[0]
    assert total == len(turns)
    folded = store.db.execute(
        "SELECT count(*) FROM short_term_turns WHERE scope_key = ? AND folded = 1", (key,)
    ).fetchone()[0]
    assert folded >= 1


def test_hard_event_cap_enforced(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000, hard_event_cap=2)
    for i in range(5):
        store.append(SCOPE, "user", f"turn number {i}")
    active = store.recent(SCOPE)
    # Hard cap bounds the active window even though the token budget is huge.
    assert len(active) <= 2
    assert active[-1] == ("user", "turn number 4")


def test_recent_honours_explicit_smaller_budget(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    for i in range(4):
        store.append(SCOPE, "user", f"message {i} content here")
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
        store.append(SCOPE, "user", f"a fairly long message number {i} to exceed the budget")
    # No summary produced, but the window is still bounded by folding.
    assert store.summary(SCOPE) == ""
    assert (
        store._active_tokens(store._active(scope_key(SCOPE))) <= 8 or len(store.recent(SCOPE)) == 1
    )


def test_clear_removes_turns_and_summary(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=8)
    for i in range(4):
        store.append(SCOPE, "user", f"message {i} with enough tokens to trigger summary folding")
    store.clear(SCOPE)
    assert store.recent(SCOPE) == []
    assert store.summary(SCOPE) == ""


def test_scopes_are_isolated(tmp_path):
    store = _sqlite_store(tmp_path, token_budget=10_000)
    a = Scope(level=ScopeLevel.SESSION, session_id="run-a")
    b = Scope(level=ScopeLevel.SESSION, session_id="run-b")
    store.append(a, "user", "alpha")
    store.append(b, "user", "beta")
    assert store.recent(a) == [("user", "alpha")]
    assert store.recent(b) == [("user", "beta")]


@pytest.mark.pgvector
def test_postgres_budget_overflow_summarizes(pgvector_dsn):
    store = ShortTermStore(
        "external", pgvector_dsn, ShortTermTierConfig(token_budget=8), _fake_summarizer
    )
    scope = Scope(level=ScopeLevel.SESSION, session_id="pg-" + uuid.uuid4().hex[:8])
    for i in range(4):
        store.append(scope, "user", f"a reasonably long postgres turn number {i} about deployments")
    summary, active = store.context(scope)
    assert summary
    assert active
    store.clear(scope)
    store.close()
