"""Cluster-free output tests for kaos agent tools."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from typer.testing import CliRunner

from kaos_cli.main import app

runner = CliRunner()


@contextmanager
def _forward(*args, **kwargs):
    yield "http://127.0.0.1:19000"


def _mock_tools(monkeypatch):
    monkeypatch.setattr(
        "kaos_cli.agent.tools.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="8000"),
    )
    monkeypatch.setattr("kaos_cli.agent.tools.port_forward", _forward)
    data = {
        "agent": "assistant",
        "tools": [
            {
                "name": "search_memory",
                "description": "Search entitled memory.",
                "parameters_json_schema": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["session", "agent", "store"],
                        }
                    },
                },
            }
        ],
    }
    monkeypatch.setattr(
        "kaos_cli.agent.tools.httpx.get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: data,
        ),
    )
    return data


def test_agent_tools_json_output_shape(monkeypatch):
    expected = _mock_tools(monkeypatch)

    result = runner.invoke(
        app, ["agent", "tools", "assistant", "-n", "support", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == expected


def test_agent_tools_human_output_includes_name_and_schema(monkeypatch):
    _mock_tools(monkeypatch)

    result = runner.invoke(app, ["agent", "tools", "assistant"])

    assert result.exit_code == 0
    assert "search_memory" in result.output
    assert '"enum": [' in result.output
    assert '"session"' in result.output
