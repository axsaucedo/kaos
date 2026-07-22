"""Scoped list endpoint contract tests."""

import uuid

from fastapi.testclient import TestClient

from kaos_memory.app import MemoryService, create_app
from kaos_memory.config import LocalStorage, ShortTermTierConfig, StorageConfig
from kaos_memory.contract import Scope, ScopeLevel
from kaos_memory.stores import LongTermStore, ShortTermStore
from tests._fakes import DeterministicEmbedder


def _service(tmp_path, offline_models):
    storage = StorageConfig(
        type="local",
        local=LocalStorage(
            path=str(tmp_path / "longterm"),
            collection_name="list_" + uuid.uuid4().hex[:8],
        ),
    )
    longterm = LongTermStore(
        storage,
        offline_models["summarization"],
        offline_models["embedding"],
    )
    longterm._memory.embedding_model = DeterministicEmbedder()
    short_term = ShortTermStore(
        "local",
        str(tmp_path / "shortterm.db"),
        ShortTermTierConfig(),
        lambda prior, turns: prior,
        group=longterm.group,
    )
    return (
        longterm,
        short_term,
        TestClient(create_app(MemoryService(longterm=longterm, short_term=short_term))),
    )


def test_list_isolates_every_scope_and_returns_session_tiers(tmp_path, offline_models):
    longterm, short_term, client = _service(tmp_path, offline_models)
    first = Scope(
        level=ScopeLevel.USER,
        principal="alice",
        agent_client_id="agent-a",
        session_id="session-1",
    )
    second = Scope(
        level=ScopeLevel.USER,
        principal="bob",
        agent_client_id="agent-b",
        session_id="session-2",
    )
    longterm.add(first, "alice session one", infer=False)
    longterm.add(second, "bob session two", infer=False)
    longterm._memory.add(
        "foreign store group",
        infer=False,
        user_id="mallory",
        agent_id="agent-c",
        metadata={"kaos_run": "session-3", "kaos_group": "another-store"},
    )
    short_term.add(first, [("user", "alice recent turn")])
    short_term.add(second, [("user", "bob recent turn")])

    cases = [
        (
            {"level": "session", "session_id": "session-1"},
            {"alice session one"},
        ),
        (
            {"level": "agent", "agent_client_id": "agent-a", "session_id": "session-1"},
            {"alice session one"},
        ),
        (
            {"level": "user", "principal": "alice", "session_id": "session-1"},
            {"alice session one"},
        ),
        (
            {"level": "store", "session_id": "session-1"},
            {"alice session one", "bob session two"},
        ),
    ]

    for scope, expected in cases:
        response = client.post("/v1/list", json={"scope": scope})

        assert response.status_code == 200
        body = response.json()
        assert {fact["memory"] for fact in body["long_term"]["facts"]} == expected
        assert "foreign store group" not in str(body["long_term"]["facts"])
        assert body["short_term"]["window"] == [["user", "alice recent turn"]]
        assert "bob recent turn" not in str(body["short_term"])


def test_list_rejects_incomplete_scope_before_store_access(tmp_path, offline_models):
    _, _, client = _service(tmp_path, offline_models)

    response = client.post("/v1/list", json={"scope": {"level": "agent"}})

    assert response.status_code == 400
    assert response.json() == {"error": "incomplete agent scope"}
