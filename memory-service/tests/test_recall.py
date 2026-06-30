"""Synchronous recall endpoint tests."""

from fastapi.testclient import TestClient

from kaos_memory.config import WorkingTierConfig
from kaos_memory.service import MemoryService, create_app
from kaos_memory.working import WorkingStore


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


def _working(tmp_path):
    return WorkingStore("local", str(tmp_path / "w.db"), WorkingTierConfig(), lambda p, f: p)


def _client(longterm, working):
    return TestClient(create_app(MemoryService(longterm=longterm, working=working)))


USER_SCOPE = {"level": "user", "principal": "alice"}


def test_recall_returns_facts_and_working_context(tmp_path):
    working = _working(tmp_path)
    longterm = _FakeLongTerm(facts=[{"memory": "alice prefers dark mode", "score": 0.9}])
    scope = {"level": "user", "principal": "alice", "session_id": "s1"}
    # Seed working turns under the same owner key.
    from kaos_memory.scope import Scope, ScopeLevel

    s = Scope(level=ScopeLevel.USER, principal="alice")
    working.append(s, "user", "hello there")
    working.append(s, "assistant", "hi alice")

    resp = _client(longterm, working).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "preferences"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is False
    # Native Mem0 fields pass through unmodified.
    assert body["facts"][0]["score"] == 0.9
    assert body["working"]["recent"] == [["user", "hello there"], ["assistant", "hi alice"]]
    assert "alice prefers dark mode" in body["block"]
    assert "## Recent turns" in body["block"]


def test_recall_degrades_to_working_only_on_longterm_failure(tmp_path):
    working = _working(tmp_path)
    from kaos_memory.scope import Scope, ScopeLevel

    working.append(
        Scope(level=ScopeLevel.USER, principal="alice"), "user", "remember the budget is 5000"
    )
    longterm = _FakeLongTerm(fail=True)

    resp = _client(longterm, working).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "budget"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    assert body["facts"] == []
    assert "budget is 5000" in body["block"]


def test_recall_can_exclude_working(tmp_path):
    working = _working(tmp_path)
    longterm = _FakeLongTerm(facts=[{"memory": "fact one"}])
    resp = _client(longterm, working).post(
        "/v1/recall",
        json={"scope": USER_SCOPE, "query": "x", "include_working": False},
    )
    body = resp.json()
    assert body["working"]["recent"] == []
    assert "fact one" in body["block"]
    assert "## Recent turns" not in body["block"]
