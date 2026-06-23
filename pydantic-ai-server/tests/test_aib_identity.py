"""Unit tests for the managed actor-token lifecycle (acquire + refresh + fail-closed)."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

import aib
from aib import identity


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Isolate each test: clear env + the process-global manager."""
    for var in (
        "AGENT_AUTH_TOKEN_ENDPOINT",
        "AGENT_AUTH_ISSUER",
        "AGENT_AUTH_CLIENT_ID",
        "AGENT_AUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    identity.reset_manager()
    aib.ctx.replace({})
    yield
    identity.reset_manager()
    aib.ctx.replace({})


class _Recorder:
    """Records grant POSTs and returns scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, data=None, timeout=None):
        self.calls.append(dict(data or {}))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _resp(status, json_body):
    return httpx.Response(
        status, json=json_body, request=httpx.Request("POST", "http://b/oauth2/token")
    )


def _manager(monkeypatch, recorder, *, refresh_fraction=0.2):
    monkeypatch.setattr(httpx, "post", recorder)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "kaos-agent-default-researcher")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "s3cr3t")
    return identity.instrument_agent_identity(refresh_fraction=refresh_fraction)


def test_no_credentials_is_inert(monkeypatch):
    mgr = identity.instrument_agent_identity()
    assert mgr is None
    assert identity.get_manager() is None
    assert aib.actor_token() is None


def test_token_endpoint_derived_from_issuer(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_ISSUER", "http://broker/")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "sec")
    mgr = identity.instrument_agent_identity()
    assert mgr is not None
    assert mgr._token_endpoint == "http://broker/oauth2/token"


def test_first_call_mints_and_caches(monkeypatch):
    rec = _Recorder([_resp(200, {"access_token": "tok-1", "expires_in": 300})])
    _manager(monkeypatch, rec)
    assert aib.actor_token() == "tok-1"
    # Second call within TTL serves the cache without re-POSTing.
    assert aib.actor_token() == "tok-1"
    assert len(rec.calls) == 1
    assert rec.calls[0]["grant_type"] == "client_credentials"
    assert rec.calls[0]["client_id"] == "kaos-agent-default-researcher"
    assert rec.calls[0]["client_secret"] == "s3cr3t"


def test_refresh_ahead_reacquires_past_threshold(monkeypatch):
    rec = _Recorder(
        [
            _resp(200, {"access_token": "tok-1", "expires_in": 100}),
            _resp(200, {"access_token": "tok-2", "expires_in": 100}),
        ]
    )
    mgr = _manager(monkeypatch, rec, refresh_fraction=0.2)
    assert mgr.token() == "tok-1"
    # Simulate crossing the refresh-ahead threshold (80% of lifetime elapsed).
    mgr._refresh_at = 0.0
    assert mgr.token() == "tok-2"
    assert len(rec.calls) == 2


def test_concurrent_callers_single_flight(monkeypatch):
    rec = _Recorder([_resp(200, {"access_token": "tok", "expires_in": 300})])
    mgr = _manager(monkeypatch, rec)

    results = []

    def _worker():
        results.append(mgr.token())

    import threading

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["tok"] * 8
    assert len(rec.calls) == 1  # single-flighted


def test_endpoint_failure_fails_closed(monkeypatch):
    def _boom(url, data=None, timeout=None):
        raise httpx.ConnectError("broker down", request=httpx.Request("POST", url))

    mgr = _manager(monkeypatch, _Recorder([]))
    monkeypatch.setattr(httpx, "post", _boom)
    with pytest.raises(identity.AIBUnavailable):
        mgr.token()


def test_missing_access_token_fails_closed(monkeypatch):
    rec = _Recorder([_resp(200, {"expires_in": 300})])
    mgr = _manager(monkeypatch, rec)
    with pytest.raises(identity.AIBUnavailable):
        mgr.token()


def test_valid_cache_survives_refresh_failure(monkeypatch):
    rec = _Recorder([_resp(200, {"access_token": "tok-1", "expires_in": 100})])
    mgr = _manager(monkeypatch, rec, refresh_fraction=0.2)
    assert mgr.token() == "tok-1"

    # Past refresh-ahead but still within lifetime; broker now fails.
    mgr._refresh_at = 0.0

    def _boom(url, data=None, timeout=None):
        raise httpx.ConnectError("broker down", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _boom)
    # Still-valid cached token is served rather than failing the request.
    assert mgr.token() == "tok-1"


def test_force_refresh_reacquires(monkeypatch):
    rec = _Recorder(
        [
            _resp(200, {"access_token": "tok-1", "expires_in": 300}),
            _resp(200, {"access_token": "tok-2", "expires_in": 300}),
        ]
    )
    mgr = _manager(monkeypatch, rec)
    assert mgr.token() == "tok-1"
    assert mgr.force_refresh() == "tok-2"
    assert len(rec.calls) == 2


def test_credential_uses_file_secret(monkeypatch, tmp_path):
    secret_file = tmp_path / "client_secret"
    secret_file.write_text("file-secret")
    rec = _Recorder([_resp(200, {"access_token": "tok", "expires_in": 300})])
    monkeypatch.setattr(httpx, "post", rec)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "env-secret")
    mgr = identity.instrument_agent_identity(client_secret_file=str(secret_file))
    assert mgr is not None
    assert mgr.token() == "tok"
    assert rec.calls[0]["client_secret"] == "file-secret"


def test_credential_reloads_on_mtime_change(monkeypatch, tmp_path):
    secret_file = tmp_path / "client_secret"
    secret_file.write_text("secret-v1")
    os.utime(secret_file, (1000, 1000))
    rec = _Recorder(
        [
            _resp(200, {"access_token": "tok-1", "expires_in": 100}),
            _resp(200, {"access_token": "tok-2", "expires_in": 100}),
        ]
    )
    monkeypatch.setattr(httpx, "post", rec)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    mgr = identity.instrument_agent_identity(
        client_secret_file=str(secret_file), refresh_fraction=0.2
    )
    assert mgr is not None
    assert mgr.token() == "tok-1"
    assert rec.calls[0]["client_secret"] == "secret-v1"

    secret_file.write_text("secret-v2")
    os.utime(secret_file, (2000, 2000))
    mgr._refresh_at = 0.0
    assert mgr.token() == "tok-2"
    assert rec.calls[1]["client_secret"] == "secret-v2"


def test_credential_env_fallback_when_no_file(monkeypatch):
    rec = _Recorder([_resp(200, {"access_token": "tok", "expires_in": 300})])
    monkeypatch.setattr(httpx, "post", rec)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "env-secret")
    mgr = identity.instrument_agent_identity()
    assert mgr is not None
    assert mgr.token() == "tok"
    assert rec.calls[0]["client_secret"] == "env-secret"


def test_credential_missing_file_falls_back_to_env(monkeypatch, tmp_path):
    rec = _Recorder([_resp(200, {"access_token": "tok", "expires_in": 300})])
    monkeypatch.setattr(httpx, "post", rec)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "env-secret")
    missing = tmp_path / "does-not-exist"
    mgr = identity.instrument_agent_identity(client_secret_file=str(missing))
    assert mgr is not None
    assert mgr.token() == "tok"
    assert rec.calls[0]["client_secret"] == "env-secret"


def test_401_reloads_credential_and_retries(monkeypatch, tmp_path):
    secret_file = tmp_path / "client_secret"
    secret_file.write_text("stale-secret")
    os.utime(secret_file, (1000, 1000))

    state = {"n": 0}

    def _post(url, data=None, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            secret_file.write_text("fresh-secret")
            os.utime(secret_file, (2000, 2000))
            return _resp(401, {"error": "invalid_client"})
        return _resp(200, {"access_token": "tok", "expires_in": 300})

    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    mgr = identity.instrument_agent_identity(client_secret_file=str(secret_file))
    assert mgr is not None
    assert mgr.token() == "tok"
    assert state["n"] == 2


def test_async_token_mints(monkeypatch):
    captured = {"calls": 0}

    class _FakeAsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            captured["calls"] += 1
            return _resp(200, {"access_token": "atok", "expires_in": 300})

    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "sec")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    identity.instrument_agent_identity()

    async def _run():
        first = await aib.actor_token_async()
        second = await aib.actor_token_async()
        return first, second

    first, second = asyncio.run(_run())
    assert first == "atok"
    assert second == "atok"
    assert captured["calls"] == 1


# --- reactive 401 retry in outbound httpx instrumentation ---------------------


def _configured_manager(monkeypatch, mint_token="fresh-token"):
    """Configure a managed identity whose force_refresh mints ``mint_token``."""

    def _post(url, data=None, timeout=None):
        return _resp(200, {"access_token": mint_token, "expires_in": 300})

    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "sec")
    return identity.instrument_agent_identity()


def test_outbound_401_refreshes_and_replays_once(monkeypatch):
    _configured_manager(monkeypatch, mint_token="fresh-token")
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request.headers.get("x-agent-authorization"))
        if len(seen) == 1:
            return httpx.Response(401)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    request.headers["x-agent-authorization"] = "Bearer stale-token"
    response = client.send(request)

    assert response.status_code == 200
    assert len(seen) == 2  # one retry only
    assert seen[0] == "Bearer stale-token"
    assert seen[1] == "Bearer fresh-token"  # replayed with the refreshed token


def test_outbound_401_no_manager_does_not_retry(monkeypatch):
    identity.reset_manager()
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request)
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    request.headers["x-agent-authorization"] = "Bearer stale-token"
    response = client.send(request)

    assert response.status_code == 401
    assert len(seen) == 1  # no retry without a managed identity


def test_outbound_non_401_does_not_retry(monkeypatch):
    _configured_manager(monkeypatch)
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    request.headers["x-agent-authorization"] = "Bearer stale-token"
    response = client.send(request)

    assert response.status_code == 500
    assert len(seen) == 1  # only 401 triggers a retry


def test_outbound_401_without_actor_header_does_not_retry(monkeypatch):
    mgr = _configured_manager(monkeypatch)
    assert mgr is not None
    monkeypatch.setattr(mgr, "token", lambda: None)  # no token to inject
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request)
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    response = client.send(request)

    assert response.status_code == 401
    assert len(seen) == 1  # no actor token was carried, so no refresh/replay


def test_outbound_async_401_refreshes_and_replays_once(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_TOKEN_ENDPOINT", "http://broker/oauth2/token")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "sec")
    mgr = identity.instrument_agent_identity()
    assert mgr is not None

    async def _fake_refresh():
        return "fresh-async"

    monkeypatch.setattr(mgr, "force_refresh_async", _fake_refresh)
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request.headers.get("x-agent-authorization"))
        if len(seen) == 1:
            return httpx.Response(401)
        return httpx.Response(200)

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            request = client.build_request("GET", "http://upstream/api")
            request.headers["x-agent-authorization"] = "Bearer stale-token"
            return await client.send(request)

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert seen == ["Bearer stale-token", "Bearer fresh-async"]


def test_outbound_injects_managed_actor_token_when_none_present(monkeypatch):
    _configured_manager(monkeypatch, mint_token="minted-actor")
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request.headers.get("x-agent-authorization"))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    response = client.send(request)

    assert response.status_code == 200
    assert seen == ["Bearer minted-actor"]


def test_outbound_does_not_override_existing_actor_token(monkeypatch):
    _configured_manager(monkeypatch, mint_token="minted-actor")
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request.headers.get("x-agent-authorization"))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    request.headers["x-agent-authorization"] = "Bearer caller-supplied"
    client.send(request)

    assert seen == ["Bearer caller-supplied"]


def test_outbound_no_manager_injects_nothing(monkeypatch):
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request.headers.get("x-agent-authorization"))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    request = client.build_request("GET", "http://upstream/api")
    client.send(request)

    assert seen == [None]


def test_outbound_async_injects_managed_actor_token(monkeypatch):
    mgr = _configured_manager(monkeypatch, mint_token="minted-async")
    assert mgr is not None
    mgr.token()  # prime the cache via the mocked sync grant so no async network call is made
    aib.instrument_httpx()

    seen = []

    def _handler(request):
        seen.append(request.headers.get("x-agent-authorization"))
        return httpx.Response(200)

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            request = client.build_request("GET", "http://upstream/api")
            return await client.send(request)

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert seen == ["Bearer minted-async"]
