"""Cluster-free tests for central memory CLI commands."""

import json

import pytest
from typer.testing import CliRunner

from kaos_cli.main import app
from kaos_cli.memory import (
    MemoryCLIError,
    build_scope,
    parse_include,
    resolve_memory_store,
)

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
        ("store", {}, {"level": "store"}),
        (
            "session",
            {"session": "s1", "user": "alice"},
            {"level": "session", "session_id": "s1", "principal": "alice"},
        ),
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
        ("store", {"agent": "assistant"}, "store scope does not take"),
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
        return {
            "long_term": {"facts": [{"memory": "known fact"}], "block": ""},
            "degraded": False,
        }

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
            "-q",
            "preferences",
            "--top-k",
            "4",
            "--include",
            "s,l",
            "-n",
            "support",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["long_term"]["facts"] == [{"memory": "known fact"}]
    assert captured["path"] == "/v1/recall"
    assert captured["payload"] == {
        "scope": {
            "level": "agent",
            "agent_client_id": "kaos://agent/support/assistant",
        },
        "include": ["short_term", "long_term"],
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
        ["memory", "recall", "--scope", "store", "--json"],
    )

    assert result.exit_code == 0
    assert captured == {
        "path": "/v1/list",
        "payload": {
            "scope": {"level": "store"},
            "include": ["short_term", "medium_term", "long_term"],
        },
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
            "-q",
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
        ["memory", "forget", "--scope", "store", "--yes"],
    )

    assert result.exit_code == 1
    assert '{"forgotten": true, "degraded": true}' in result.output


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (None, ["short_term", "medium_term", "long_term"]),
        (["S,m", "long-term", "s"], ["short_term", "medium_term", "long_term"]),
        (["a", "l"], ["short_term", "medium_term", "long_term"]),
    ],
)
def test_parse_include_aliases_commas_repeats_and_dedupes(values, expected):
    assert parse_include(values) == expected


def test_parse_include_rejects_unknown_value():
    with pytest.raises(MemoryCLIError, match="unknown --include value"):
        parse_include(["archive"])


def test_query_requires_long_term_include(monkeypatch):
    monkeypatch.setattr(
        "kaos_cli.memory._effective_namespace",
        lambda namespace: pytest.fail("Kubernetes should not be consulted"),
    )

    result = runner.invoke(
        app,
        ["memory", "recall", "--scope", "store", "-q", "x", "--include", "s,m"],
    )

    assert result.exit_code == 1
    assert "requires long-term" in result.output


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


def _fake_jwt(sub: str) -> str:
    import base64

    payload = (
        base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    )
    return f"header.{payload}.signature"


def test_resolve_user_substitutes_cached_login_sub(tmp_path, monkeypatch):
    from kaos_cli.memory import _resolve_user

    config = tmp_path / ".kaos-config.yaml"
    config.write_text(
        json.dumps(
            {"sessions": {"alice": {"token": _fake_jwt("sub-123"), "active": True}}}
        )
    )
    monkeypatch.chdir(tmp_path)
    assert _resolve_user("alice") == "sub-123"


def test_resolve_user_passes_through_unknown_and_raw_subs(tmp_path, monkeypatch):
    from kaos_cli.memory import _resolve_user

    config = tmp_path / ".kaos-config.yaml"
    config.write_text(
        json.dumps({"sessions": {"alice": {"token": _fake_jwt("sub-123")}}})
    )
    monkeypatch.chdir(tmp_path)
    assert _resolve_user("bob") == "bob"
    assert _resolve_user("9dfcf3f2-7ec0-485d") == "9dfcf3f2-7ec0-485d"
    assert _resolve_user(None) is None


def test_resolve_user_without_config_is_identity(tmp_path, monkeypatch):
    from kaos_cli.memory import _resolve_user

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _resolve_user("alice") == "alice"


def test_resolve_user_survives_malformed_token(tmp_path, monkeypatch):
    from kaos_cli.memory import _resolve_user

    config = tmp_path / ".kaos-config.yaml"
    config.write_text(json.dumps({"sessions": {"alice": {"token": "not-a-jwt"}}}))
    monkeypatch.chdir(tmp_path)
    assert _resolve_user("alice") == "alice"
