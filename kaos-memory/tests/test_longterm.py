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


def test_agent_and_session_scopes_isolated(tmp_path, offline_models):
    store = _local_store(tmp_path, offline_models)
    agent = Scope(level=ScopeLevel.PRIVATE, agent_client_id="agent-a")
    session = Scope(level=ScopeLevel.SESSION, session_id="run-1")
    store.add(agent, "agent private fact about ports", infer=False)
    store.add(session, "session ephemeral fact about ports", infer=False)

    agent_hits = store.recall(agent, "ports", top_k=10)
    assert any("agent private" in h["memory"] for h in agent_hits)
    # The session fact must not surface under the agent scope.
    assert all("ephemeral" not in h["memory"] for h in agent_hits)


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
