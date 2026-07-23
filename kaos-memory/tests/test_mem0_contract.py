"""Pinned Mem0 semantics that KAOS compound attribution depends on."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest

os.environ["MEM0_TELEMETRY"] = "False"

from mem0 import Memory

from kaos_memory.contract import Scope, ScopeLevel
from kaos_memory.stores import LongTermStore


class CountingLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fact = "unset"

    def generate_response(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return json.dumps({"memory": [{"text": self.fact}]})


class DeterministicEmbedder:
    """Map every text to the same vector so filters, not similarity, prove isolation."""

    def embed(self, text: str, memory_action: str | None = None) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

    def embed_batch(self, texts: list[str], memory_action: str = "add") -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def mem0(tmp_path):
    collection = "contract_" + uuid.uuid4().hex[:12]
    config = {
        "llm": {"provider": "openai", "config": {"model": "stub", "api_key": "stub"}},
        "embedder": {
            "provider": "openai",
            "config": {"model": "stub", "api_key": "stub", "embedding_dims": 4},
        },
        "vector_store": {
            "provider": "chroma",
            "config": {"collection_name": collection, "path": str(tmp_path / "chroma")},
        },
        "history_db_path": str(tmp_path / "history.db"),
    }
    memory = Memory.from_config(config)
    llm = CountingLLM()
    memory.llm = llm
    memory.embedding_model = DeterministicEmbedder()
    return memory, llm


def _add_raw(memory: Memory, text: str, **kwargs: Any) -> None:
    memory.add(text, infer=False, **kwargs)


def _texts(raw: dict[str, Any]) -> set[str]:
    return {item["memory"] for item in raw["results"]}


def _all(memory: Memory) -> dict[str, Any]:
    return memory.get_all(filters={"user_id": "*"}, top_k=100)


def test_wildcard_custom_filters_work_for_search_and_get_all(mem0):
    memory, _ = mem0
    _add_raw(memory, "group one first", user_id="u1", metadata={"kaos_group": "g1"})
    _add_raw(memory, "group one second", user_id="u2", metadata={"kaos_group": "g1"})
    _add_raw(memory, "group two", user_id="u3", metadata={"kaos_group": "g2"})
    filters = {"user_id": "*", "kaos_group": "g1"}

    searched = memory.search("equal query", filters=filters, top_k=10, threshold=0.0)
    listed = memory.get_all(filters=filters, top_k=100)

    assert _texts(searched) == {"group one first", "group one second"}
    assert _texts(listed) == {"group one first", "group one second"}


def test_custom_session_and_group_erasure_uses_filtered_ids(mem0):
    memory, _ = mem0
    _add_raw(
        memory,
        "erase by session",
        user_id="u1",
        agent_id="a1",
        metadata={"kaos_run": "r1", "kaos_group": "g1"},
    )
    _add_raw(
        memory,
        "erase by group",
        user_id="u2",
        agent_id="a2",
        metadata={"kaos_run": "r2", "kaos_group": "g1"},
    )
    _add_raw(
        memory,
        "keep other group",
        user_id="u3",
        agent_id="a3",
        metadata={"kaos_run": "r3", "kaos_group": "g2"},
    )
    store = object.__new__(LongTermStore)
    store._memory = memory
    store.group = "g1"

    store.delete_scope(Scope(level=ScopeLevel.SESSION, session_id="r1"))
    assert _texts(_all(memory)) == {"erase by group", "keep other group"}

    store.delete_scope(Scope(level=ScopeLevel.STORE))
    assert _texts(_all(memory)) == {"keep other group"}


def test_compound_write_is_one_extraction_and_one_record(mem0):
    memory, llm = mem0
    llm.fact = "one compound fact"

    result = memory.add(
        [{"role": "user", "content": "remember this"}],
        user_id="u1",
        agent_id="a1",
        metadata={"kaos_run": "r1", "kaos_group": "g1"},
    )
    records = memory.vector_store.list(top_k=100)[0]

    assert len(llm.calls) == 1
    assert len(result["results"]) == 1
    assert len(records) == 1
    assert records[0].payload["user_id"] == "u1"
    assert records[0].payload["agent_id"] == "a1"
    assert records[0].payload["kaos_run"] == "r1"
    assert records[0].payload["kaos_group"] == "g1"


def test_single_entity_filters_retrieve_compound_records_without_leakage(mem0):
    memory, _ = mem0
    _add_raw(memory, "u1 a1", user_id="u1", agent_id="a1")
    _add_raw(memory, "u2 a2", user_id="u2", agent_id="a2")
    _add_raw(memory, "u1 a2", user_id="u1", agent_id="a2")

    user_hits = memory.search("equal query", filters={"user_id": "u1"}, top_k=10, threshold=0.0)
    agent_hits = memory.search("equal query", filters={"agent_id": "a1"}, top_k=10, threshold=0.0)

    assert _texts(user_hits) == {"u1 a1", "u1 a2"}
    assert _texts(agent_hits) == {"u1 a1"}
    assert "u2 a2" not in _texts(user_hits)
    assert "u1 a2" not in _texts(agent_hits)


def test_two_entity_filter_requires_matching_user_and_agent(mem0):
    memory, _ = mem0
    _add_raw(memory, "u1 a1", user_id="u1", agent_id="a1")
    _add_raw(memory, "u2 a1", user_id="u2", agent_id="a1")
    _add_raw(memory, "u1 a2", user_id="u1", agent_id="a2")

    filters = Scope(
        level=ScopeLevel.AGENT,
        principal="u1",
        agent_client_id="a1",
    ).search_filters()
    searched = memory.search("equal query", filters=filters, top_k=10, threshold=0.0)
    listed = memory.get_all(filters=filters, top_k=100)

    assert _texts(searched) == {"u1 a1"}
    assert _texts(listed) == {"u1 a1"}


def test_cross_session_dedup_consolidates_compound_record(mem0):
    memory, llm = mem0
    llm.fact = "same durable preference"
    first = {"kaos_run": "r1", "kaos_group": "g1"}
    second = {"kaos_run": "r2", "kaos_group": "g1"}

    memory.add("first turn", user_id="u1", agent_id="a1", metadata=first)
    memory.add("second turn", user_id="u1", agent_id="a1", metadata=second)

    assert len(llm.calls) == 2
    assert _texts(_all(memory)) == {"same durable preference"}
    assert len(memory.vector_store.list(top_k=100)[0]) == 1
