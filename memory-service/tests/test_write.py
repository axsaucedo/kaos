"""Write endpoint tests: synchronous working append + scheduled extraction."""

import threading

from fastapi.testclient import TestClient

from kaos_memory.config import WorkingTierConfig
from kaos_memory.scope import Scope, ScopeLevel
from kaos_memory.service import MemoryService, create_app
from kaos_memory.working import WorkingStore

USER_SCOPE = {"level": "user", "principal": "bob"}


class _RecordingLongTerm:
    """Records writes; lets the test block extraction until released."""

    def __init__(self):
        self.writes = []
        self.gate = threading.Event()

    def write(self, scope, messages, infer=True):
        self.gate.wait(timeout=5)
        self.writes.append((scope, messages, infer))

    def ping(self):
        return None


def _working(tmp_path):
    return WorkingStore("local", str(tmp_path / "w.db"), WorkingTierConfig(), lambda p, f: p)


def _client(longterm, working, scheduler):
    return TestClient(
        create_app(MemoryService(longterm=longterm, working=working, scheduler=scheduler))
    )


def test_write_returns_before_extraction_and_persists_working_row(tmp_path):
    working = _working(tmp_path)
    longterm = _RecordingLongTerm()  # extraction blocks until gate is set
    captured = []
    client = _client(longterm, working, captured.append)

    resp = client.post(
        "/v1/write", json={"scope": USER_SCOPE, "role": "user", "content": "deploy nginx"}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] is True and body["scheduled"] is True

    # The working row is present synchronously, before any extraction runs.
    recent = working.recent(Scope(level=ScopeLevel.USER, principal="bob"))
    assert recent == [("user", "deploy nginx")]
    # Extraction was scheduled (captured) but not yet executed.
    assert len(captured) == 1
    assert longterm.writes == []


def test_strict_surfaces_working_append_failure(tmp_path):
    class _BrokenWorking:
        def append(self, *a, **k):
            raise RuntimeError("disk full")

    client = _client(_RecordingLongTerm(), _BrokenWorking(), lambda t: None)
    resp = client.post(
        "/v1/write",
        json={"scope": USER_SCOPE, "role": "user", "content": "x", "failure_mode": "strict"},
    )
    assert resp.status_code == 500
    assert resp.json()["accepted"] is False


def test_soft_swallows_schedule_failure(tmp_path):
    working = _working(tmp_path)

    def _broken_scheduler(thunk):
        raise RuntimeError("scheduler down")

    client = _client(_RecordingLongTerm(), working, _broken_scheduler)
    resp = client.post(
        "/v1/write",
        json={"scope": USER_SCOPE, "role": "user", "content": "y", "failure_mode": "soft"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["scheduled"] is False
    assert body["degraded"] is True
    # The durable working append still happened.
    assert working.recent(Scope(level=ScopeLevel.USER, principal="bob")) == [("user", "y")]
