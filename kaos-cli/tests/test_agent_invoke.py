from types import SimpleNamespace

import httpx
from typer.testing import CliRunner

from kaos_cli.main import app
from kaos_cli.agent.invoke import invoke_command


class FakeProcess:
    stderr = None

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self):
        pass


def test_invoke_waits_for_delayed_port_forward(monkeypatch, capsys):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="8000"),
    )
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr("signal.signal", lambda *args: None)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    attempts = 0

    def get(_url, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("not ready")
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ready"}}]},
        ),
    )

    invoke_command("test-agent", "test-ns", "hello", 19001, False)

    assert attempts == 3
    assert "ready" in capsys.readouterr().out


def test_invoke_without_namespace_uses_current_context(monkeypatch):
    run_calls = []

    def run(cmd, **_kwargs):
        run_calls.append(cmd)
        if cmd[:3] == ["kubectl", "config", "view"]:
            return SimpleNamespace(returncode=0, stdout="current-context-ns")
        return SimpleNamespace(returncode=0, stdout="8000")

    popen_calls = []
    monkeypatch.setattr("subprocess.run", run)
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda cmd, **_kwargs: popen_calls.append(cmd) or FakeProcess(),
    )
    monkeypatch.setattr("signal.signal", lambda *args: None)
    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: httpx.Response(200))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_args, **_kwargs: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ready"}}]},
        ),
    )

    invoke_command("test-agent", None, "hello", 19001, False)

    assert run_calls[0][:3] == ["kubectl", "config", "view"]
    assert run_calls[1][-2:] == ["-n", "current-context-ns"]
    assert popen_calls[0][-2:] == ["-n", "current-context-ns"]
    assert "default" not in run_calls[1]

def test_invoke_sends_session_header(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="8000")
    )
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr("signal.signal", lambda *args: None)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200))

    captured = {}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ready"}}]},
        )

    monkeypatch.setattr(httpx, "post", post)

    invoke_command("test-agent", "test-ns", "hello", 19001, False, session="ticket-42")

    assert captured["headers"] == {"X-Session-ID": "ticket-42"}


def test_invoke_session_flag_is_wired(monkeypatch):
    captured = {}

    def invoke(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("kaos_cli.agent.invoke_command", invoke)

    result = CliRunner().invoke(
        app,
        ["agent", "invoke", "assistant", "--message", "hello", "--session", "ticket-42"],
    )

    assert result.exit_code == 0
    assert captured["session"] == "ticket-42"
