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
        "subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="8000")
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
