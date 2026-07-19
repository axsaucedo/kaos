"""Write endpoint tests: synchronous short-term append + scheduled extraction."""

import threading

from fastapi.testclient import TestClient

from kaos_memory.config import MemorySettings, ShortTermTierConfig
from kaos_memory.stores import Scope, ScopeLevel
from kaos_memory.app import MemoryService, create_app
from kaos_memory.stores import ShortTermStore

USER_SCOPE = {"level": "user", "principal": "bob", "session_id": "session-1"}


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


def _short_term(tmp_path, cfg=None):
    return ShortTermStore(
        "local", str(tmp_path / "w.db"), cfg or ShortTermTierConfig(), lambda p, f: p
    )


def _client(longterm, short_term, scheduler):
    return TestClient(
        create_app(MemoryService(longterm=longterm, short_term=short_term, scheduler=scheduler))
    )


def _write(client, content, **extra):
    return client.post(
        "/v1/write", json={"attribution": USER_SCOPE, "role": "user", "content": content, **extra}
    )


def test_write_posture_rejects_missing_required_identities(tmp_path):
    service = MemoryService(longterm=_RecordingLongTerm(), short_term=_short_term(tmp_path))
    client = TestClient(create_app(service, settings=MemorySettings(require_principal=True)))
    response = client.post(
        "/v1/write",
        json={"attribution": {"agent_client_id": "agent-a", "session_id": "s"}, "role": "user", "content": "x"},
    )
    assert response.status_code == 403
    assert "principal" in response.json()["error"]


def test_write_posture_accepts_complete_attribution(tmp_path):
    service = MemoryService(longterm=_RecordingLongTerm(), short_term=_short_term(tmp_path))
    settings = MemorySettings(require_principal=True, require_agent_identity=True)
    client = TestClient(create_app(service, settings=settings))
    response = client.post(
        "/v1/write",
        json={"attribution": {"principal": "alice", "agent_client_id": "agent-a", "session_id": "s"}, "role": "user", "content": "x"},
    )
    assert response.status_code == 200


def test_write_buffers_without_eviction_then_extracts_the_evicted_batch(tmp_path):
    # hard_event_cap=1 makes the second turn evict the first, triggering extraction.
    short_term = _short_term(tmp_path, ShortTermTierConfig(hard_event_cap=1))
    longterm = _RecordingLongTerm()  # extraction blocks until gate is set
    captured = []
    client = _client(longterm, short_term, captured.append)

    # First turn is buffered in the window: nothing has been evicted, so nothing is scheduled.
    first = _write(client, "deploy nginx")
    assert first.status_code == 200
    assert first.json()["scheduled"] is False
    assert captured == []

    # Second turn pushes the window over the cap, evicting the first turn and scheduling
    # extraction of that evicted batch (not the just-written turn).
    second = _write(client, "scale to three")
    assert second.status_code == 202
    body = second.json()
    assert body["accepted"] is True and body["scheduled"] is True

    # The newest turn is present synchronously; extraction was scheduled but not executed.
    recent = short_term.active_window(
        Scope(level=ScopeLevel.USER, principal="bob", session_id="session-1")
    )
    assert recent == [("user", "scale to three")]
    assert len(captured) == 1
    assert longterm.writes == []

    # When the gate opens, extraction runs over the evicted batch.
    longterm.gate.set()
    captured[0]()
    assert len(longterm.writes) == 1
    _, messages, _ = longterm.writes[0]
    assert messages == [{"role": "user", "content": "deploy nginx"}]


def test_batch_write_appends_all_turns_and_extracts_combined_eviction(tmp_path):
    # A single request carrying several turns; the cap forces evictions and one combined
    # extraction of the evicted batch.
    short_term = _short_term(tmp_path, ShortTermTierConfig(hard_event_cap=1))
    longterm = _RecordingLongTerm()
    longterm.gate.set()  # let extraction run immediately when invoked
    captured = []
    client = _client(longterm, short_term, captured.append)

    resp = client.post(
        "/v1/write",
        json={
            "attribution": USER_SCOPE,
            "turns": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
            ],
        },
    )
    assert resp.status_code == 202
    assert resp.json()["scheduled"] is True

    # The newest turn remains in the window; the older turns were evicted.
    recent = short_term.active_window(
        Scope(level=ScopeLevel.USER, principal="bob", session_id="session-1")
    )
    assert recent == [("user", "three")]

    # A single extraction was scheduled over the combined evicted batch, in order.
    assert len(captured) == 1
    captured[0]()
    assert len(longterm.writes) == 1
    _, messages, _ = longterm.writes[0]
    assert messages == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
    ]


def test_strict_surfaces_short_term_append_failure(tmp_path):
    class _BrokenShortTerm:
        def append(self, *a, **k):
            raise RuntimeError("disk full")

    client = _client(_RecordingLongTerm(), _BrokenShortTerm(), lambda t: None)
    resp = client.post(
        "/v1/write",
        json={"attribution": USER_SCOPE, "role": "user", "content": "x", "failure_mode": "strict"},
    )
    assert resp.status_code == 500
    assert resp.json()["accepted"] is False


def test_soft_swallows_schedule_failure(tmp_path):
    short_term = _short_term(tmp_path, ShortTermTierConfig(hard_event_cap=1))

    def _broken_scheduler(thunk):
        raise RuntimeError("scheduler down")

    client = _client(_RecordingLongTerm(), short_term, _broken_scheduler)
    # First turn buffers without scheduling; the second evicts and hits the broken scheduler.
    assert _write(client, "x").json()["scheduled"] is False
    resp = _write(client, "y", failure_mode="soft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["scheduled"] is False
    assert body["degraded"] is True
    # The durable short-term append still happened (newest turn retained after eviction).
    assert short_term.active_window(
        Scope(level=ScopeLevel.USER, principal="bob", session_id="session-1")
    ) == [("user", "y")]
