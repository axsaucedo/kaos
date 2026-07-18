"""Unit tests for the long-term Mem0 adapter (scope isolation + erasure)."""

import uuid

import pytest

from kaos_memory.config import ExternalStorage, LocalStorage, StorageConfig
from kaos_memory.stores import LongTermStore
from kaos_memory.stores import Scope, ScopeLevel
from tests._fakes import DeterministicEmbedder


def _local_store(tmp_path, models):
    storage = StorageConfig(
        type="local",
        local=LocalStorage(path=str(tmp_path), collection_name="t_" + uuid.uuid4().hex[:8]),
    )
    store = LongTermStore(storage, models["summarization"], models["embedding"])
    # Swap in the offline deterministic embedder before the first write.
    store._memory.embedding_model = DeterministicEmbedder()
    return store


def _external_store(dsn, models):
    storage = StorageConfig(
        type="external",
        external=ExternalStorage(
            dsn=dsn, collection_name="t_" + uuid.uuid4().hex[:8], embedding_dims=64
        ),
    )
    store = LongTermStore(storage, models["summarization"], models["embedding"])
    store._memory.embedding_model = DeterministicEmbedder()
    return store


def _assert_owner_isolation(store):
    alice = Scope(level=ScopeLevel.USER, principal="alice")
    bob = Scope(level=ScopeLevel.USER, principal="bob")
    # Identical text -> identical embedding -> exact nearest neighbours.
    store.add(alice, "the deployment uses port 8080", infer=False)
    store.add(bob, "the deployment uses port 8080", infer=False)
    store.add(alice, "alice private api token", infer=False)

    a_hits = store.recall(alice, "what port does the deployment use", top_k=10)
    b_hits = store.recall(bob, "what port does the deployment use", top_k=10)
    assert any("8080" in h["memory"] for h in a_hits)
    assert any("8080" in h["memory"] for h in b_hits)
    # No cross-owner leakage even though vectors are identical (pre-filtering).
    assert {h["id"] for h in a_hits}.isdisjoint({h["id"] for h in b_hits})
    return alice, bob


def test_local_scope_isolation(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    _assert_owner_isolation(store)


def test_local_delete_scope_removes_only_that_owner(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    alice, bob = _assert_owner_isolation(store)

    store.delete_scope(alice)
    assert store.recall(alice, "what port does the deployment use", top_k=10) == []
    # Bob's memory is untouched.
    assert any(
        "8080" in h["memory"]
        for h in store.recall(bob, "what port does the deployment use", top_k=10)
    )


def test_local_delete_session_uses_custom_attribution(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    first = Scope(
        level=ScopeLevel.SESSION,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )
    second = first.model_copy(update={"session_id": "run-2"})
    store.add(first, "first session fact", infer=False)
    store.add(second, "second session fact", infer=False)

    store.delete_scope(first)

    assert store.recall(first, "session fact", top_k=10) == []
    assert [hit["memory"] for hit in store.recall(second, "session fact", top_k=10)] == [
        "second session fact"
    ]


def test_local_delete_group_removes_store_group(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    alice = Scope(
        level=ScopeLevel.GROUP,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )
    bob = Scope(
        level=ScopeLevel.GROUP,
        principal="bob",
        agent_client_id="agent-b",
        session_id="run-2",
    )
    store.add(alice, "alice group fact", infer=False)
    store.add(bob, "bob group fact", infer=False)

    store.delete_scope(Scope(level=ScopeLevel.GROUP))

    assert store.recall(Scope(level=ScopeLevel.GROUP), "group fact", top_k=10) == []


def test_agent_read_includes_same_agent_session_contribution(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    agent = Scope(level=ScopeLevel.AGENT, agent_client_id="agent-a")
    session = Scope(
        level=ScopeLevel.SESSION,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )
    store.add(agent, "agent private fact about ports", infer=False)
    store.add(session, "session ephemeral fact about ports", infer=False)

    agent_hits = store.recall(agent, "ports", top_k=10)
    assert any("agent private" in h["memory"] for h in agent_hits)
    assert any("session ephemeral" in h["memory"] for h in agent_hits)

    session_hits = store.recall(session, "ports", top_k=10)
    assert any("session ephemeral" in h["memory"] for h in session_hits)
    assert all("agent private" not in h["memory"] for h in session_hits)


def test_group_read_uses_collection_attribution(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    scope = Scope(
        level=ScopeLevel.GROUP,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )
    store.add(scope, "group deployment fact", infer=False)

    hits = store.recall(Scope(level=ScopeLevel.GROUP), "deployment", top_k=10)

    assert [hit["memory"] for hit in hits] == ["group deployment fact"]


@pytest.mark.pgvector
def test_external_scope_isolation(pgvector_dsn, offline_models):
    store = _external_store(pgvector_dsn, offline_models)
    _assert_owner_isolation(store)


@pytest.mark.pgvector
def test_external_delete_scope(pgvector_dsn, offline_models):
    store = _external_store(pgvector_dsn, offline_models)
    alice, bob = _assert_owner_isolation(store)
    store.delete_scope(alice)
    assert store.recall(alice, "what port does the deployment use", top_k=10) == []
    assert store.recall(bob, "what port does the deployment use", top_k=10)


def test_extraction_system_prompt_threads_into_mem0_config(tmp_path, offline_models, monkeypatch):
    captured = {}

    class _StubMemory:
        embedding_model = None

        @classmethod
        def from_config(cls, config):
            captured["config"] = config
            return cls()

    monkeypatch.setattr("kaos_memory.stores.Memory", _StubMemory)
    storage = StorageConfig(
        type="local",
        local=LocalStorage(path=str(tmp_path), collection_name="t_" + uuid.uuid4().hex[:8]),
    )

    LongTermStore(
        storage,
        offline_models["summarization"],
        offline_models["embedding"],
        system_prompt="only extract deployment facts",
    )
    assert captured["config"]["custom_fact_extraction_prompt"] == "only extract deployment facts"

    captured.clear()
    LongTermStore(storage, offline_models["summarization"], offline_models["embedding"])
    assert "custom_fact_extraction_prompt" not in captured["config"]


def test_add_uses_compound_attribution_and_collection_group(tmp_path, offline_models, monkeypatch):
    captured = {}

    class _StubMemory:
        @classmethod
        def from_config(cls, config):
            return cls()

        def add(self, messages, **kwargs):
            captured.update(kwargs)
            return {"results": []}

    monkeypatch.setattr("kaos_memory.stores.Memory", _StubMemory)
    storage = StorageConfig(
        type="local",
        local=LocalStorage(path=str(tmp_path), collection_name="store-team"),
    )
    store = LongTermStore(storage, offline_models["summarization"], offline_models["embedding"])
    scope = Scope(
        level=ScopeLevel.USER,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )

    store.add(scope, "remember this", infer=False)

    assert captured == {
        "infer": False,
        "user_id": "alice",
        "agent_id": "agent-a",
        "metadata": {"kaos_run": "run-1", "kaos_group": "store-team"},
    }


def test_filtered_delete_prefers_native_mem0_support(tmp_path, offline_models, monkeypatch):
    captured = {}

    class _StubMemory:
        @classmethod
        def from_config(cls, config):
            return cls()

        def delete_all(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("kaos_memory.stores.Memory", _StubMemory)
    storage = StorageConfig(
        type="local",
        local=LocalStorage(path=str(tmp_path), collection_name="store-team"),
    )
    store = LongTermStore(storage, offline_models["summarization"], offline_models["embedding"])

    store.delete_scope(Scope(level=ScopeLevel.SESSION, session_id="run-1"))

    assert captured == {"filters": {"user_id": "*", "kaos_run": "run-1"}}


def test_filtered_delete_falls_back_to_get_all_and_ids(tmp_path, offline_models, monkeypatch):
    calls = []

    class _StubMemory:
        def __init__(self):
            self.ids = ["m1", "m2"]

        @classmethod
        def from_config(cls, config):
            return cls()

        def delete_all(self, **kwargs):
            raise TypeError("filters are unsupported")

        def get_all(self, **kwargs):
            calls.append(("get_all", kwargs))
            return {"results": [{"id": memory_id} for memory_id in self.ids]}

        def delete(self, memory_id):
            calls.append(("delete", memory_id))
            self.ids.remove(memory_id)

    monkeypatch.setattr("kaos_memory.stores.Memory", _StubMemory)
    storage = StorageConfig(
        type="local",
        local=LocalStorage(path=str(tmp_path), collection_name="store-team"),
    )
    store = LongTermStore(storage, offline_models["summarization"], offline_models["embedding"])

    store.delete_scope(Scope(level=ScopeLevel.GROUP))

    filters = {"user_id": "*", "kaos_group": "store-team"}
    assert calls == [
        ("get_all", {"filters": filters, "top_k": 1000}),
        ("delete", "m1"),
        ("delete", "m2"),
        ("get_all", {"filters": filters, "top_k": 1000}),
    ]
