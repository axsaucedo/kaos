"""Unit tests for the optional off-gateway broker client (access-check + token)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

import aib
from aib import client as aib_client
from aib import identity


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    for var in (
        "AGENT_AUTH_BASE_URL",
        "AGENT_AUTH_TOKEN_ENDPOINT",
        "AGENT_AUTH_CLIENT_ID",
        "AGENT_AUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    identity.reset_manager()
    aib.ctx.replace({})
    yield
    identity.reset_manager()
    aib.ctx.replace({})


def _response(status, json_body, url="http://broker/api/access/check"):
    return httpx.Response(status, json=json_body, request=httpx.Request("POST", url))


class _Recorder:
    """Captures POST calls and returns a scripted response."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def __call__(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "data": data, "headers": headers or {}})
        return self._response


def test_check_access_allowed(monkeypatch):
    rec = _Recorder(_response(200, {"allowed": True, "reason": "ok", "actor": "agent-x"}))
    monkeypatch.setattr(httpx, "post", rec)
    c = aib_client.Client(base_url="http://broker")
    decision = c.check_access("svc:db", "read")
    assert decision.allowed is True
    assert decision.actor == "agent-x"
    assert rec.calls[0]["url"] == "http://broker/api/access/check"
    assert rec.calls[0]["json"] == {"resource": "svc:db", "action": "read"}


def test_check_access_includes_actor_token_from_ctx(monkeypatch):
    rec = _Recorder(_response(200, {"allowed": True}))
    monkeypatch.setattr(httpx, "post", rec)
    aib.ctx.replace({"actor_token": "tok-123", "principal": "user@example.com"})
    c = aib_client.Client(base_url="http://broker")
    c.check_access("svc:db")
    assert rec.calls[0]["json"]["actor_token"] == "tok-123"
    assert rec.calls[0]["headers"]["x-principal"] == "user@example.com"


def test_require_access_raises_on_deny(monkeypatch):
    rec = _Recorder(_response(200, {"allowed": False, "reason": "not_permitted"}))
    monkeypatch.setattr(httpx, "post", rec)
    c = aib_client.Client(base_url="http://broker")
    with pytest.raises(aib_client.AccessDenied) as excinfo:
        c.require_access("svc:db")
    assert excinfo.value.decision.reason == "not_permitted"


def test_require_access_raises_reauth_on_recoverable_denial(monkeypatch):
    rec = _Recorder(
        _response(
            200, {"allowed": False, "reason": "reauth_required", "reauth_url": "http://login"}
        )
    )
    monkeypatch.setattr(httpx, "post", rec)
    c = aib_client.Client(base_url="http://broker")
    with pytest.raises(aib_client.ReauthenticationRequired) as excinfo:
        c.require_access("svc:db")
    assert excinfo.value.reauth_url == "http://login"


def test_check_access_transport_error_is_unavailable(monkeypatch):
    def _boom(*args, **kwargs):
        raise httpx.ConnectError("down", request=httpx.Request("POST", "http://broker"))

    monkeypatch.setattr(httpx, "post", _boom)
    c = aib_client.Client(base_url="http://broker")
    with pytest.raises(identity.AIBUnavailable):
        c.check_access("svc:db")


def test_exchange_token(monkeypatch):
    rec = _Recorder(
        _response(
            200,
            {"access_token": "delegated-xyz", "token_type": "Bearer", "expires_in": 600},
            url="http://broker/oauth2/token",
        )
    )
    monkeypatch.setattr(httpx, "post", rec)
    c = aib_client.Client(base_url="http://broker")
    result = c.exchange_token("subject-tok", audience="svc:db", scopes="read")
    assert result.access_token == "delegated-xyz"
    assert result.expires_in == 600
    form = rec.calls[0]["data"]
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form["subject_token"] == "subject-tok"
    assert form["audience"] == "svc:db"
    assert rec.calls[0]["url"] == "http://broker/oauth2/token"


def test_get_token_uses_subject_token_from_ctx(monkeypatch):
    rec = _Recorder(_response(200, {"access_token": "deleg"}, url="http://broker/oauth2/token"))
    monkeypatch.setattr(httpx, "post", rec)
    aib.ctx.replace({"subject_token": "user-jwt"})
    c = aib_client.Client(base_url="http://broker")
    result = c.get_token("svc:db")
    assert result.access_token == "deleg"
    assert rec.calls[0]["data"]["subject_token"] == "user-jwt"
    assert rec.calls[0]["data"]["audience"] == "svc:db"


def test_get_token_without_subject_is_unavailable(monkeypatch):
    c = aib_client.Client(base_url="http://broker")
    with pytest.raises(identity.AIBUnavailable):
        c.get_token("svc:db")


def test_token_endpoint_derived_from_base_url():
    c = aib_client.Client(base_url="http://broker/")
    assert c._token_endpoint == "http://broker/oauth2/token"


def test_async_check_access_allowed(monkeypatch):
    captured = {}

    class _FakeAsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, data=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return _response(200, {"allowed": True, "actor": "agent-y"}, url=url)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    c = aib_client.AsyncClient(base_url="http://broker")
    decision = asyncio.run(c.check_access("svc:db"))
    assert decision.allowed is True
    assert decision.actor == "agent-y"
    assert captured["url"] == "http://broker/api/access/check"
