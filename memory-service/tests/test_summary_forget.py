"""Server-side rolling summary and forget endpoint tests."""

from fastapi.testclient import TestClient

from kaos_memory.config import WorkingTierConfig
from kaos_memory.scope import Scope, ScopeLevel
from kaos_memory.service import MemoryService, create_app
from kaos_memory.working import WorkingStore

USER_SCOPE = {"level": "user", "principal": "carol"}


class _RecordingLongTerm:
    def __init__(self):
        self.recalls = []
        self.deleted = []
        self.facts = []

    def recall(self, scope, query, top_k=10):
        return self.facts

    def write(self, scope, messages, infer=True):
        return []

    def delete_scope(self, scope):
        self.deleted.append(scope)

    def ping(self):
        return None


def _client(longterm, working):
    return TestClient(
        create_app(MemoryService(longterm=longterm, working=working, scheduler=lambda t: None))
    )


def test_overflow_summarizes_server_side(tmp_path):
    calls = []

    def summarizer(prior, folded):
        calls.append((prior, list(folded)))
        return (prior + " " + " ".join(c for _, c in folded)).strip()

    # Tiny budget forces folding into the rolling summary on the server.
    working = WorkingStore(
        "local", str(tmp_path / "w.db"), WorkingTierConfig(token_budget=4), summarizer
    )
    scope = Scope(level=ScopeLevel.USER, principal="carol")
    for i in range(5):
        working.append(scope, "user", f"message number {i} with several tokens here")

    assert calls, "summarizer should have been invoked server-side on overflow"
    assert working.summary(scope) != ""


def test_forget_clears_both_tiers(tmp_path):
    working = WorkingStore("local", str(tmp_path / "w.db"), WorkingTierConfig(), lambda p, f: p)
    longterm = _RecordingLongTerm()
    scope = Scope(level=ScopeLevel.USER, principal="carol")
    working.append(scope, "user", "something to remember")
    assert working.recent(scope)

    resp = _client(longterm, working).post("/v1/forget", json={"scope": USER_SCOPE})
    assert resp.status_code == 200
    assert resp.json()["forgotten"] is True
    assert working.recent(scope) == []
    assert working.summary(scope) == ""
    assert len(longterm.deleted) == 1


def test_forget_soft_degrades_on_longterm_failure(tmp_path):
    class _BrokenDelete(_RecordingLongTerm):
        def delete_scope(self, scope):
            raise RuntimeError("delete failed")

    working = WorkingStore("local", str(tmp_path / "w.db"), WorkingTierConfig(), lambda p, f: p)
    scope = Scope(level=ScopeLevel.USER, principal="carol")
    working.append(scope, "user", "x")

    resp = _client(_BrokenDelete(), working).post(
        "/v1/forget", json={"scope": USER_SCOPE, "failure_mode": "soft"}
    )
    assert resp.status_code == 200
    assert resp.json()["degraded"] is True
    # Working tier was still cleared despite the long-term failure.
    assert working.recent(scope) == []
