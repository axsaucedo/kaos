"""Tests for the tier-level service settings: long_term_enabled, default_top_k,
and the score_threshold / rerank pass-through to Mem0 search."""

import uuid

from fastapi.testclient import TestClient

from kaos_memory.app import MemoryService, create_app
from kaos_memory.config import LocalStorage, MemorySettings, ShortTermTierConfig, StorageConfig
from kaos_memory.stores import LongTermStore, Scope, ScopeLevel, ShortTermStore

USER_SCOPE = {"level": "user", "principal": "alice", "session_id": "s1"}


class _RecordingLongTerm:
    """Records recall/add calls; can be made to fail to prove degraded semantics."""

    def __init__(self, fail=False):
        self.recalls = []
        self.writes = []
        self._fail = fail

    def recall(self, scope, query, top_k=10):
        if self._fail:
            raise RuntimeError("vector store unreachable")
        self.recalls.append(top_k)
        return [{"memory": "alice prefers dark mode"}]

    def get_all(self, scope):
        if self._fail:
            raise RuntimeError("vector store unreachable")
        return [{"memory": "alice prefers dark mode"}]

    def add(self, scope, messages, infer=True):
        self.writes.append((messages, infer))

    def ping(self):
        return None


def _short_term(tmp_path, cfg=None):
    return ShortTermStore(
        "local", str(tmp_path / "w.db"), cfg or ShortTermTierConfig(), lambda p, f: p
    )


def _client(longterm, short_term, **service_kwargs):
    service = MemoryService(longterm=longterm, short_term=short_term, **service_kwargs)
    return TestClient(create_app(service))


def test_settings_expose_tier_defaults():
    s = MemorySettings()
    assert s.long_term_enabled is True
    assert s.default_top_k == 10
    assert s.score_threshold is None
    assert s.rerank is False


def test_long_term_disabled_write_skips_extraction(tmp_path):
    # hard_event_cap=1 forces an eviction on the second turn; with the long-term
    # tier disabled the evicted batch must not be scheduled for extraction.
    short_term = _short_term(tmp_path, ShortTermTierConfig(hard_event_cap=1))
    longterm = _RecordingLongTerm()
    scheduled = []
    client = _client(longterm, short_term, scheduler=scheduled.append, long_term_enabled=False)

    for content in ("deploy nginx", "scale to three"):
        resp = client.post(
            "/v1/write", json={"attribution": USER_SCOPE, "role": "user", "content": content}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] is True
        assert body["scheduled"] is False
        assert body["degraded"] is False
    assert scheduled == []
    assert longterm.writes == []

    # The conversational tiers keep working: the newest turn is in the window.
    recent = short_term.active_window(
        Scope(level=ScopeLevel.USER, principal="alice", session_id="s1")
    )
    assert recent == [("user", "scale to three")]


def test_long_term_disabled_recall_returns_empty_facts_not_degraded(tmp_path):
    # Even a long-term store that would fail is never contacted: facts stay empty
    # and degraded stays false — disabled is configuration, not failure.
    short_term = _short_term(tmp_path)
    client = _client(_RecordingLongTerm(fail=True), short_term, long_term_enabled=False)

    resp = client.post("/v1/recall", json={"scope": USER_SCOPE, "query": "preferences"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["facts"] == []
    assert body["block"] == ""
    assert body["degraded"] is False

    resp = client.post("/v1/list", json={"scope": USER_SCOPE})
    assert resp.json()["facts"] == [] and resp.json()["degraded"] is False


def test_recall_uses_default_top_k_when_request_omits_it(tmp_path):
    longterm = _RecordingLongTerm()
    client = _client(longterm, _short_term(tmp_path), default_top_k=3)

    client.post("/v1/recall", json={"scope": USER_SCOPE, "query": "q"})
    assert longterm.recalls == [3]

    # An explicit request value still wins over the configured default.
    client.post("/v1/recall", json={"scope": USER_SCOPE, "query": "q", "top_k": 7})
    assert longterm.recalls == [3, 7]


def test_score_threshold_and_rerank_pass_through_to_mem0_search(
    tmp_path, offline_models, monkeypatch
):
    captured = {}

    class _StubMemory:
        @classmethod
        def from_config(cls, config):
            return cls()

        def search(self, query, **kwargs):
            captured.update(kwargs)
            return {"results": []}

    monkeypatch.setattr("kaos_memory.stores.Memory", _StubMemory)
    storage = StorageConfig(
        type="local",
        local=LocalStorage(path=str(tmp_path), collection_name="t_" + uuid.uuid4().hex[:8]),
    )
    scope = Scope(level=ScopeLevel.USER, principal="alice")

    # Defaults: neither threshold nor rerank appear in the call shape.
    store = LongTermStore(storage, offline_models["summarization"], offline_models["embedding"])
    store.recall(scope, "query", top_k=5)
    assert "threshold" not in captured and "rerank" not in captured

    captured.clear()
    store = LongTermStore(
        storage,
        offline_models["summarization"],
        offline_models["embedding"],
        score_threshold=0.4,
        rerank=True,
    )
    store.recall(scope, "query", top_k=5)
    assert captured["threshold"] == 0.4
    assert captured["rerank"] is True
    assert captured["top_k"] == 5
