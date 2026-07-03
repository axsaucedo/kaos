"""Write endpoint tests: synchronous short-term append + scheduled extraction."""

import threading

from fastapi.testclient import TestClient

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.stores import Scope, ScopeLevel
from kaos_memory.app import MemoryService, create_app
from kaos_memory.stores import ShortTermStore

USER_SCOPE = {"level": "user", "principal": "bob"}


class _RecordingLongTerm:
    """Records writes; lets the test block extraction until released."""

    def __init__(self):
        self.writes = []
        self.gate = threading.Event()

    def add(self, scope, messages, infer=True):
        self.gate.wait(timeout=5)
        self.writes.append((scope, messages, infer))

    def ping(self):
        return None


def _short_term(tmp_path):
    return ShortTermStore("local", str(tmp_path / "w.db"), ShortTermTierConfig(), lambda p, f: p)


def _client(longterm, short_term, scheduler):
    return TestClient(
        create_app(MemoryService(longterm=longterm, short_term=short_term, scheduler=scheduler))
    )


def test_write_returns_before_extraction_and_persists_short_term_row(tmp_path):
    short_term = _short_term(tmp_path)
    longterm = _RecordingLongTerm()  # extraction blocks until gate is set
    captured = []
    client = _client(longterm, short_term, captured.append)

    resp = client.post(
        "/v1/write", json={"scope": USER_SCOPE, "role": "user", "content": "deploy nginx"}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] is True and body["scheduled"] is True

    # The short-term row is present synchronously, before any extraction runs.
    recent = short_term.active_window(Scope(level=ScopeLevel.USER, principal="bob"))
    assert recent == [("user", "deploy nginx")]
    # Extraction was scheduled (captured) but not yet executed.
    assert len(captured) == 1
    assert longterm.writes == []


def test_strict_surfaces_short_term_append_failure(tmp_path):
    class _BrokenShortTerm:
        def append(self, *a, **k):
            raise RuntimeError("disk full")

    client = _client(_RecordingLongTerm(), _BrokenShortTerm(), lambda t: None)
    resp = client.post(
        "/v1/write",
        json={"scope": USER_SCOPE, "role": "user", "content": "x", "failure_mode": "strict"},
    )
    assert resp.status_code == 500
    assert resp.json()["accepted"] is False


def test_soft_swallows_schedule_failure(tmp_path):
    short_term = _short_term(tmp_path)

    def _broken_scheduler(thunk):
        raise RuntimeError("scheduler down")

    client = _client(_RecordingLongTerm(), short_term, _broken_scheduler)
    resp = client.post(
        "/v1/write",
        json={"scope": USER_SCOPE, "role": "user", "content": "y", "failure_mode": "soft"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["scheduled"] is False
    assert body["degraded"] is True
    # The durable short-term append still happened.
    assert short_term.active_window(Scope(level=ScopeLevel.USER, principal="bob")) == [
        ("user", "y")
    ]
