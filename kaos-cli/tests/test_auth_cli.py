import base64
import json
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
