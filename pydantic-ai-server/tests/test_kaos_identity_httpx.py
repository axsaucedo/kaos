"""Unit tests for kaos_identity.instrument_httpx outbound header injection."""

import kaos_identity
import httpx
import pytest
import respx


@pytest.fixture(autouse=True)
def _patch_and_clear():
    kaos_identity.instrument_httpx()  # idempotent — safe to call per test
    kaos_identity.ctx.replace({})
    yield
    kaos_identity.ctx.replace({})


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
