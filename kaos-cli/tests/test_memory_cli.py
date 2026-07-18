"""Cluster-free tests for central memory CLI commands."""

import json

import pytest
from typer.testing import CliRunner

from kaos_cli.main import app
from kaos_cli.memory import MemoryCLIError, build_scope, resolve_memory_store

runner = CliRunner()


@pytest.mark.parametrize(
    ("level", "kwargs", "expected"),
    [
        ("session", {"session": "s1"}, {"level": "session", "session_id": "s1"}),
        (
            "agent",
            {"agent": "assistant"},
            {
                "level": "agent",
                "agent_client_id": "kaos://agent/support/assistant",
            },
        ),
        ("user", {"user": "alice"}, {"level": "user", "principal": "alice"}),
        ("group", {}, {"level": "group"}),
    ],
)
def test_build_scope_matches_memory_contract(level, kwargs, expected):
    assert build_scope(level, "support", **kwargs) == expected


@pytest.mark.parametrize(
    ("level", "kwargs", "message"),
    [
        ("session", {}, "--session is required"),
        ("agent", {"user": "alice"}, "--agent is the only owner flag"),
        ("user", {"user": "alice", "session": "s1"}, "--user is the only owner flag"),
        ("group", {"agent": "assistant"}, "group scope does not take"),
    ],
)
def test_build_scope_rejects_owner_mismatch(level, kwargs, message):
    with pytest.raises(ValueError, match=message):
        build_scope(level, "support", **kwargs)


def test_resolve_memory_store_uses_status_endpoint(monkeypatch):
    monkeypatch.setattr(
        "kaos_cli.memory._memory_stores",
        lambda namespace: [
            {
                "metadata": {"name": "support-memory"},
                "status": {
                    "endpoint": "http://memorystore-support-memory.support.svc.cluster.local:8080"
                },
            }
        ],
    )

    assert resolve_memory_store(None, "support") == (
        "support-memory",
        "svc/memorystore-support-memory",
        8080,
    )


def test_resolve_memory_store_requires_name_for_multiple(monkeypatch):
    monkeypatch.setattr(
        "kaos_cli.memory._memory_stores",
        lambda namespace: [
            {"metadata": {"name": "one"}},
            {"metadata": {"name": "two"}},
        ],
    )

    with pytest.raises(MemoryCLIError, match="--store is required"):
        resolve_memory_store(None, "support")
    assert resolve_memory_store("two", "support") == (
        "two",
        "svc/memorystore-two",
        8080,
    )


def _mock_cluster(monkeypatch):
    monkeypatch.setattr(
        "kaos_cli.memory._effective_namespace", lambda namespace: namespace or "ctx"
    )
    monkeypatch.setattr(
        "kaos_cli.memory.resolve_memory_store",
        lambda store, namespace: (
            store or "only-store",
            "svc/memorystore-only-store",
            8080,
        ),
    )


def test_recall_query_sends_qualified_agent_scope(monkeypatch):
    _mock_cluster(monkeypatch)
    captured = {}

    def request(method, path, payload, target, remote_port, namespace):
        captured.update(
            method=method,
            path=path,
            payload=payload,
            target=target,
            remote_port=remote_port,
            namespace=namespace,
        )
        return {"facts": [{"memory": "known fact"}], "degraded": False}

    monkeypatch.setattr("kaos_cli.memory._request", request)

    result = runner.invoke(
        app,
        [
            "memory",
            "recall",
            "--scope",
            "agent",
            "--agent",
            "assistant",
            "--query",
            "preferences",
            "--top-k",
            "4",
            "--short-term",
            "-n",
            "support",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["facts"] == [{"memory": "known fact"}]
    assert captured["path"] == "/v1/recall"
    assert captured["payload"] == {
        "scope": {
            "level": "agent",
            "agent_client_id": "kaos://agent/support/assistant",
        },
        "include_short_term": True,
        "query": "preferences",
        "top_k": 4,
    }


def test_recall_all_uses_list_path(monkeypatch):
    _mock_cluster(monkeypatch)
    captured = {}

    def request(method, path, payload, target, remote_port, namespace):
        captured.update(path=path, payload=payload)
        return {"facts": []}

    monkeypatch.setattr("kaos_cli.memory._request", request)

    result = runner.invoke(
        app,
        ["memory", "recall", "--scope", "group", "--all", "--json"],
    )

    assert result.exit_code == 0
    assert captured == {
        "path": "/v1/list",
        "payload": {"scope": {"level": "group"}, "include_short_term": False},
    }


def test_recall_rejects_owner_mismatch_before_cluster_access(monkeypatch):
    monkeypatch.setattr(
        "kaos_cli.memory._effective_namespace",
        lambda namespace: pytest.fail("Kubernetes should not be consulted"),
    )

    result = runner.invoke(
        app,
        [
            "memory",
            "recall",
            "--scope",
            "user",
            "--agent",
            "assistant",
            "--query",
            "x",
        ],
    )

    assert result.exit_code == 1
    assert "--user is the only owner flag" in result.output


def test_forget_confirmation_decline_does_not_call_service(monkeypatch):
    _mock_cluster(monkeypatch)
    monkeypatch.setattr(
        "kaos_cli.memory._request", lambda *args: pytest.fail("forget should not run")
    )

    result = runner.invoke(
        app,
        ["memory", "forget", "--scope", "user", "--user", "alice"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert 'Resolved scope: {"level": "user", "principal": "alice"}' in result.output
    assert "Erase all memory at scope" in result.output
    assert "Aborted." in result.output


def test_forget_yes_prints_result_and_degraded_is_failure(monkeypatch):
    _mock_cluster(monkeypatch)
    monkeypatch.setattr(
        "kaos_cli.memory._request",
        lambda *args: {"forgotten": True, "degraded": True},
    )

    result = runner.invoke(
        app,
        ["memory", "forget", "--scope", "group", "--yes"],
    )

    assert result.exit_code == 1
    assert '{"forgotten": true, "degraded": true}' in result.output


def test_forget_yes_returns_successful_service_result(monkeypatch):
    _mock_cluster(monkeypatch)
    monkeypatch.setattr(
        "kaos_cli.memory._request",
        lambda *args: {"forgotten": True, "degraded": False},
    )

    result = runner.invoke(
        app,
        ["memory", "forget", "--scope", "session", "--session", "s1", "--yes"],
    )

    assert result.exit_code == 0
    assert '{"forgotten": true, "degraded": false}' in result.output
