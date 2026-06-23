"""Unit tests for the managed actor-token lifecycle (acquire + refresh + fail-closed)."""

from __future__ import annotations

import asyncio

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
    yield
    identity.reset_manager()


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
