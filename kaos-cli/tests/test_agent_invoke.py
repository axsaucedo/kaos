from types import SimpleNamespace

import httpx

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
