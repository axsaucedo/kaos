from types import SimpleNamespace
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from kaos_cli.main import app


runner = CliRunner()


def test_new_install_flags_wire_existing_auth_behavior(tmp_path):
    with patch("kaos_cli.system.install_command") as install:
        result = runner.invoke(
            app,
            [
                "system", "install", "--gateway-enabled", "--gateway-strict",
                "--authz-enabled", "--agent-auth", "oidc", "--user-auth", "keycloak",
            ],
        )
    assert result.exit_code == 0, result.output
    kwargs = install.call_args.kwargs
    assert kwargs["gateway_api_strict"] is True
    assert kwargs["identity_provider"] == "oidc"
    assert kwargs["pdp_enabled"] is True
    assert kwargs["user_auth"] is True


def test_create_cli_config_contents(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with patch("kaos_cli.system.install_command"):
        result = runner.invoke(
            app,
            [
                "system", "install", "--gateway-enabled", "--authz-enabled",
                "--user-auth", "keycloak", "--create-cli-config",
            ],
        )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((tmp_path / ".kaos-config.yaml").read_text())
    assert data["gateway"]["through_gateway"] is True
    assert data["gateway"]["address"].startswith("http://kaos-gateway.")
    assert data["auth"]["client_id"] == "kaos"
    assert data["auth"]["realm"] == "kaos"
    assert data["namespace"] == "kaos-system"


def test_system_status_component_table():
    items = []
    for name, ready, replicas in [
        ("envoy-gateway", 1, 1), ("keycloak", 1, 1),
        ("kaos-pdp", 2, 2), ("kaos-operator-controller-manager", 1, 1),
    ]:
        items.append({
            "metadata": {"name": name},
            "spec": {"replicas": replicas},
            "status": {"readyReplicas": ready},
        })
    completed = SimpleNamespace(returncode=0, stdout=__import__("json").dumps({"items": items}), stderr="")
    with patch("kaos_cli.system.status.subprocess.run", return_value=completed):
        result = runner.invoke(app, ["system", "status"])
    assert result.exit_code == 0
    assert "gateway           ready" in result.output
    assert "login service     ready   (keycloak)" in result.output
    assert "access-control    ready   (2/2 replicas)" in result.output
    assert "sync service      ready" in result.output


def test_access_control_off_scales_pdp_to_zero():
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")
    with patch("kaos_cli.system.subprocess.run", return_value=completed) as run:
        result = runner.invoke(app, ["system", "access-control", "--off"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "✓ access-control off"
    assert run.call_args_list[0].args[0] == [
        "kubectl", "scale", "deployment/kaos-pdp", "-n", "kaos-system", "--replicas=0"
    ]
