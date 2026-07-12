"""Unit tests for kaos_identity.instrument_httpx outbound header injection."""

import base64
import json
from urllib.parse import parse_qs

import kaos_identity
import httpx
import pytest
import respx


@pytest.fixture(autouse=True)
def _patch_and_clear(monkeypatch):
    kaos_identity.instrument_httpx()  # idempotent — safe to call per test
    kaos_identity.ctx.replace({})
    for name in (
        "KAOS_TOKEN_EXCHANGE_CONFIG",
        "AGENT_AUTH_CLIENT_ID",
        "AGENT_AUTH_CLIENT_SECRET",
        "AGENT_AUTH_CLIENT_SECRET_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    kaos_identity.ctx.replace({})


def _jwt(**claims):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


def _exchange_env(monkeypatch):
    monkeypatch.setenv(
        "KAOS_TOKEN_EXCHANGE_CONFIG",
        json.dumps(
            {
                "issuer": "https://keycloak.example/realms/kaos",
                "token_endpoint": "https://keycloak.example/realms/kaos/protocol/openid-connect/token",
                "audience": "token-exchange-broker",
                "targets": ["https://api.github.com/"],
            }
        ),
    )
    monkeypatch.setenv("AGENT_AUTH_CLIENT_ID", "kaos-agent-demo-researcher")
    monkeypatch.setenv("AGENT_AUTH_CLIENT_SECRET", "secret")


@respx.mock
@pytest.mark.asyncio
async def test_async_injects_both_identities():
    route = respx.post("http://downstream/run").respond(200)
    kaos_identity.ctx.update(
        {
            "request_id": "req-9",
            "principal": "keycloak://kaos/alice",
            "subject_token": "user-token",
            "actor": "kaos://agent/default/researcher",
            "actor_token": "actor-token",
        }
    )
    async with httpx.AsyncClient() as client:
        await client.post("http://downstream/run")

    sent = route.calls.last.request.headers
    assert sent["x-request-id"] == "req-9"
    assert sent["x-principal"] == "keycloak://kaos/alice"
    assert sent["authorization"] == "Bearer user-token"
    assert sent["x-actor"] == "kaos://agent/default/researcher"
    assert sent["x-agent-authorization"] == "Bearer actor-token"


@respx.mock
def test_sync_client_injects():
    route = respx.get("http://downstream/data").respond(200)
    kaos_identity.ctx["actor"] = "kaos://agent/default/a"
    with httpx.Client() as client:
        client.get("http://downstream/data")
    assert route.calls.last.request.headers["x-actor"] == "kaos://agent/default/a"


@respx.mock
@pytest.mark.asyncio
async def test_does_not_overwrite_existing_authorization():
    """A provider's own Authorization (e.g. ModelAPI API key) is preserved."""
    route = respx.post("http://modelapi/v1/chat").respond(200)
    kaos_identity.ctx.update({"subject_token": "user-token", "actor": "kaos://agent/default/a"})
    async with httpx.AsyncClient() as client:
        await client.post("http://modelapi/v1/chat", headers={"Authorization": "Bearer api-key"})

    sent = route.calls.last.request.headers
    assert sent["authorization"] == "Bearer api-key"  # not clobbered
    assert sent["x-actor"] == "kaos://agent/default/a"  # additive header still added


@respx.mock
@pytest.mark.asyncio
async def test_empty_context_injects_nothing():
    route = respx.get("http://downstream/ping").respond(200)
    async with httpx.AsyncClient() as client:
        await client.get("http://downstream/ping")
    headers = route.calls.last.request.headers
    assert "x-actor" not in headers
    assert "x-agent-authorization" not in headers


def test_instrument_httpx_is_idempotent():
    import kaos_identity.instrument as inst

    send_before = httpx.AsyncClient.send
    kaos_identity.instrument_httpx()
    kaos_identity.instrument_httpx()
    assert httpx.AsyncClient.send is send_before
    assert inst._httpx_patched is True


@respx.mock
@pytest.mark.asyncio
async def test_declared_third_party_call_remints_user_subject(monkeypatch):
    _exchange_env(monkeypatch)
    subject_token = _jwt(
        iss="https://keycloak.example/realms/kaos", sub="alice", azp="login-client"
    )
    reminted_token = _jwt(
        iss="https://keycloak.example/realms/kaos",
        sub="alice",
        azp="kaos-agent-demo-researcher",
        aud=["token-exchange-broker"],
    )
    exchange = respx.post(
        "https://keycloak.example/realms/kaos/protocol/openid-connect/token"
    ).respond(200, json={"access_token": reminted_token})
    github = respx.get("https://api.github.com/user").respond(200)
    kaos_identity.ctx.update(
        {
            "principal": "keycloak://kaos/alice",
            "subject_token": subject_token,
            "actor": "kaos://agent/demo/researcher",
            "actor_token": "actor-token",
        }
    )

    async with httpx.AsyncClient() as client:
        await client.get("https://api.github.com/user")

    form = parse_qs(exchange.calls.last.request.content.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:token-exchange"]
    assert form["subject_token"] == [subject_token]
    assert form["audience"] == ["token-exchange-broker"]
    assert exchange.calls.last.request.headers["authorization"].startswith("Basic ")
    assert github.calls.last.request.headers["authorization"] == f"Bearer {reminted_token}"
    assert github.calls.last.request.headers["x-agent-authorization"] == "Bearer actor-token"


@respx.mock
@pytest.mark.asyncio
async def test_internal_call_keeps_propagated_subject(monkeypatch):
    _exchange_env(monkeypatch)
    route = respx.get("http://modelapi/v1/models").respond(200)
    kaos_identity.ctx.update(
        {
            "principal": "keycloak://kaos/alice",
            "subject_token": "user-token",
            "actor": "kaos://agent/demo/researcher",
            "actor_token": "actor-token",
        }
    )
    async with httpx.AsyncClient() as client:
        await client.get("http://modelapi/v1/models")
    assert route.calls.last.request.headers["authorization"] == "Bearer user-token"
    assert len(respx.calls) == 1


@respx.mock
@pytest.mark.asyncio
async def test_autonomous_third_party_call_does_not_remint(monkeypatch):
    _exchange_env(monkeypatch)
    route = respx.get("https://api.github.com/user").respond(200)
    kaos_identity.ctx.update(
        {
            "principal": "kaos://agent/demo/researcher",
            "subject_token": "actor-token",
            "actor": "kaos://agent/demo/researcher",
            "actor_token": "actor-token",
        }
    )
    async with httpx.AsyncClient() as client:
        await client.get("https://api.github.com/user")
    assert route.calls.last.request.headers["authorization"] == "Bearer actor-token"
    assert len(respx.calls) == 1


@respx.mock
@pytest.mark.asyncio
async def test_declared_call_without_agent_client_fails_cleanly(monkeypatch):
    _exchange_env(monkeypatch)
    monkeypatch.delenv("AGENT_AUTH_CLIENT_SECRET")
    kaos_identity.ctx.update(
        {
            "principal": "keycloak://kaos/alice",
            "subject_token": _jwt(sub="alice"),
            "actor": "kaos://agent/demo/researcher",
        }
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(kaos_identity.IdentityUnavailable, match="requires AGENT_AUTH"):
            await client.get("https://api.github.com/user")
