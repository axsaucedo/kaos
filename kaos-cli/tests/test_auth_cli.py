import base64
from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from kaos_cli.agent.invoke import plain_access_reason
from kaos_cli.auth.grant import build_access_grant
from kaos_cli.main import app


runner = CliRunner()


def test_grant_dry_run_output_shape(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["auth", "grant", "create", "--group", "researchers", "--resource", "agent/researcher", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    grant = yaml.safe_load(result.output)
    assert grant == {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "AccessGrant",
        "metadata": {"name": "researchers-to-researcher"},
        "spec": {
            "subjects": [{"kind": "Group", "name": "researchers"}],
            "resources": [{"kind": "Agent", "name": "researcher"}],
        },
    }


def test_agent_grant_accepts_comma_separated_resources():
    grant = build_access_grant(
        group=None, user=None, agent="researcher",
        resources=["mcp/notes-mcp,modelapi/chat-model"],
    )
    assert grant["spec"]["subjects"] == [{"kind": "Agent", "name": "researcher"}]
    assert [item["kind"] for item in grant["spec"]["resources"]] == ["MCPServer", "ModelAPI"]


def test_reason_to_plain_english_mapping():
    assert plain_access_reason("platform_grant_missing") == "not granted"
    assert plain_access_reason("user_grant_required") == "user not in a granted group"
    assert plain_access_reason("access-control unreachable") == "access-control unavailable (failing closed)"
    assert plain_access_reason("missing token") == "no valid identity"


def test_consent_stub_receives_arguments():
    with patch("kaos_cli.auth.consent_command") as consent:
        result = runner.invoke(app, ["auth", "connect", "github", "--user", "alice"])
    assert result.exit_code == 0
    consent.assert_called_once_with("github", "alice", disconnect=False)


def _jwt(claims):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


def test_login_caches_token_and_prints_groups(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kaos-config.yaml").write_text(
        "auth:\n  issuer: http://login/realms/kaos\n  client_id: kaos\n"
    )
    token = _jwt({"groups": ["researchers"]})
    response = SimpleNamespace(
        json=lambda: {"access_token": token},
        raise_for_status=lambda: None,
    )
    with patch("kaos_cli.auth.login.httpx.post", return_value=response) as post:
        result = runner.invoke(
            app, ["auth", "login", "alice", "--password", "secret"]
        )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "✓ logged in as alice — groups: researchers"
    assert post.call_args.kwargs["data"]["client_secret"] == "kaos-dev-secret"
    assert post.call_args.kwargs["headers"] == {"Host": "login"}
    saved = yaml.safe_load((tmp_path / ".kaos-config.yaml").read_text())
    assert saved["sessions"]["alice"]["token"] == token


def test_login_forwards_cluster_local_issuer(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kaos-config.yaml").write_text(
        "auth:\n  issuer: http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos\n"
        "  client_id: kaos\n"
    )
    token = _jwt({"groups": ["researchers"]})
    response = SimpleNamespace(
        json=lambda: {"access_token": token},
        raise_for_status=lambda: None,
    )

    @contextmanager
    def forwarded(_url):
        yield "http://127.0.0.1:12345/realms/kaos/protocol/openid-connect/token"

    with (
        patch("kaos_cli.auth.login.local_service_url", forwarded),
        patch("kaos_cli.auth.login.httpx.post", return_value=response) as post,
    ):
        result = runner.invoke(
            app, ["auth", "login", "alice", "--password", "secret"]
        )
    assert result.exit_code == 0, result.output
    assert post.call_args.args[0].startswith("http://127.0.0.1:12345/")
    assert post.call_args.kwargs["headers"] == {
        "Host": "keycloak.keycloak.svc.cluster.local:8080"
    }


def test_agent_invoke_uses_gateway_token_and_header_verdict(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kaos-config.yaml").write_text(
        "gateway:\n  address: http://gateway\n  through_gateway: true\n"
        "namespace: demo\n"
        "sessions:\n  alice:\n    token: cached-token\n    active: true\n"
    )
    response = SimpleNamespace(
        status_code=403,
        headers={"x-kaos-access-reason": "user_grant_required"},
        json=lambda: {"detail": "denied"},
        text="denied",
    )
    with patch("httpx.post", return_value=response) as post:
        result = runner.invoke(
            app,
            ["agent", "invoke", "researcher", "--user", "alice"],
        )
    assert result.exit_code == 0, result.output
    assert "✗ denied — user not in a granted group" in result.output
    assert post.call_args.args[0] == "http://gateway/demo/agent/researcher/v1/chat/completions"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer cached-token"}
    assert post.call_args.kwargs["json"]["messages"][0]["content"] == "Hello"


def test_agent_invoke_without_user_does_not_reuse_active_session(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kaos-config.yaml").write_text(
        "gateway:\n  address: http://gateway\n  through_gateway: true\n"
        "namespace: demo\n"
        "sessions:\n  alice:\n    token: cached-token\n    active: true\n"
    )
    response = SimpleNamespace(
        status_code=403, headers={}, json=lambda: {}, text=""
    )
    with (
        patch("kaos_cli.agent.invoke._is_autonomous", return_value=False),
        patch("httpx.post", return_value=response) as post,
    ):
        result = runner.invoke(app, ["agent", "invoke", "researcher"])
    assert result.exit_code == 0, result.output
    assert "✗ denied — no valid identity" in result.output
    assert post.call_args.kwargs["headers"] == {}


def test_agent_invoke_reports_fail_closed_when_pdp_is_down(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kaos-config.yaml").write_text(
        "gateway:\n  address: http://gateway\n  through_gateway: true\n"
        "namespace: demo\n"
        "sessions:\n  alice:\n    token: cached-token\n    active: true\n"
    )
    response = SimpleNamespace(
        status_code=403, headers={}, json=lambda: {}, text=""
    )
    with (
        patch("kaos_cli.agent.invoke._access_control_ready", return_value=False),
        patch("httpx.post", return_value=response),
    ):
        result = runner.invoke(
            app, ["agent", "invoke", "researcher", "--user", "alice"]
        )
    assert result.exit_code == 0, result.output
    assert "✗ denied — access-control unavailable (failing closed)" in result.output
