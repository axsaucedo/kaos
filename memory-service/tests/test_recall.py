"""Synchronous recall endpoint tests."""

from fastapi.testclient import TestClient

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.app import MemoryService, create_app
from kaos_memory.stores import ShortTermStore


class _FakeLongTerm:
    def __init__(self, facts=None, fail=False):
        self._facts = facts or []
        self._fail = fail

    def recall(self, scope, query, top_k=10):
        if self._fail:
            raise RuntimeError("vector store unreachable")
        return self._facts

    def ping(self):
        return None


def _short_term(tmp_path):
    return ShortTermStore("local", str(tmp_path / "w.db"), ShortTermTierConfig(), lambda p, f: p)


def _client(longterm, short_term):
    return TestClient(create_app(MemoryService(longterm=longterm, short_term=short_term)))


USER_SCOPE = {"level": "user", "principal": "alice"}


def test_recall_returns_facts_and_short_term_context(tmp_path):
    short_term = _short_term(tmp_path)
    longterm = _FakeLongTerm(facts=[{"memory": "alice prefers dark mode", "score": 0.9}])
    scope = {"level": "user", "principal": "alice", "session_id": "s1"}
    # Seed short-term turns under the same owner key.
    from kaos_memory.stores import Scope, ScopeLevel

    s = Scope(level=ScopeLevel.USER, principal="alice")
    short_term.add(s, "user", "hello there")
    short_term.add(s, "assistant", "hi alice")

    resp = _client(longterm, short_term).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "preferences"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is False
    # Native Mem0 fields pass through unmodified.
    assert body["facts"][0]["score"] == 0.9
    assert body["short_term"]["recent"] == [["user", "hello there"], ["assistant", "hi alice"]]
    assert "alice prefers dark mode" in body["block"]
    assert "## Recent turns" in body["block"]


def test_recall_degrades_to_short_term_only_on_longterm_failure(tmp_path):
    short_term = _short_term(tmp_path)
    from kaos_memory.stores import Scope, ScopeLevel

    short_term.add(
        Scope(level=ScopeLevel.USER, principal="alice"), "user", "remember the budget is 5000"
    )
    longterm = _FakeLongTerm(fail=True)

    resp = _client(longterm, short_term).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "budget"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    assert body["facts"] == []
    assert "budget is 5000" in body["block"]


def test_recall_can_exclude_short_term(tmp_path):
    short_term = _short_term(tmp_path)
    longterm = _FakeLongTerm(facts=[{"memory": "fact one"}])
    resp = _client(longterm, short_term).post(
        "/v1/recall",
        json={"scope": USER_SCOPE, "query": "x", "include_short_term": False},
    )
    body = resp.json()
    assert body["short_term"]["recent"] == []
    assert "fact one" in body["block"]
    assert "## Recent turns" not in body["block"]
