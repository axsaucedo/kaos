"""Tests for gateway-outcome detection on the instrumented outbound path.

A KAOS-secured gateway stamps enforcement decisions onto the response: an ext_authz
denial returns ``403`` with ``x-kaos-access-reason`` (``platform_grant_missing`` /
``user_grant_required``, no URL); an ext_proc token-exchange re-auth returns ``200``
with ``x-kaos-access-reason: third_party_reauth_required`` plus ``x-kaos-reauth-url``.
The SDK turns these into typed outcomes so the runtime can surface them; every other
response (including ordinary non-KAOS 4xx/5xx) is returned untouched.
"""

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


# --- outcome_from_response (pure header mapping) ------------------------------


def _response(status: int, headers: dict) -> httpx.Response:
    return httpx.Response(status_code=status, headers=headers)


def test_outcome_none_for_plain_response():
    assert kaos_identity.outcome_from_response(_response(200, {})) is None
    assert kaos_identity.outcome_from_response(_response(403, {})) is None
    assert kaos_identity.outcome_from_response(_response(500, {"x-other": "y"})) is None


def test_outcome_platform_grant_missing_has_no_url():
    decision = kaos_identity.outcome_from_response(
        _response(403, {"x-kaos-access-reason": "platform_grant_missing"}),
        resource="mcp.example",
    )
    assert decision is not None
    assert decision.allowed is False
    assert decision.reason == "platform_grant_missing"
    assert decision.resource == "mcp.example"
    assert decision.reauth_url is None
    assert decision.requires_reauth is False


def test_outcome_reauth_carries_url():
    decision = kaos_identity.outcome_from_response(
        _response(
            200,
            {
                "x-kaos-access-reason": "third_party_reauth_required",
                "x-kaos-reauth-url": "https://idp.example/reauth",
            },
        )
    )
    assert decision is not None
    assert decision.reason == "third_party_reauth_required"
    assert decision.reauth_url == "https://idp.example/reauth"
    assert decision.requires_reauth is True


# --- raise_for_gateway_outcome -----------------------------------------------


def test_raise_access_denied_for_ext_authz():
    with pytest.raises(kaos_identity.AccessDenied) as exc:
        kaos_identity.raise_for_gateway_outcome(
            _response(403, {"x-kaos-access-reason": "user_grant_required"})
        )
    assert not isinstance(exc.value, kaos_identity.ReauthenticationRequired)
    assert exc.value.decision.reason == "user_grant_required"


def test_raise_reauth_for_ext_proc():
    with pytest.raises(kaos_identity.ReauthenticationRequired) as exc:
        kaos_identity.raise_for_gateway_outcome(
            _response(
                200,
                {
                    "x-kaos-access-reason": "third_party_reauth_required",
                    "x-kaos-reauth-url": "https://idp.example/reauth",
                },
            )
        )
    assert exc.value.reauth_url == "https://idp.example/reauth"


def test_raise_noop_for_plain_response():
    kaos_identity.raise_for_gateway_outcome(_response(200, {}))  # no raise
    kaos_identity.raise_for_gateway_outcome(
        _response(403, {"x-app": "z"})
    )  # non-KAOS 403, no raise


# --- end-to-end through the instrumented httpx send --------------------------


@respx.mock
def test_sync_send_raises_on_ext_authz_denial():
    respx.get("http://downstream/data").respond(
        403, headers={"x-kaos-access-reason": "platform_grant_missing"}
    )
    with httpx.Client() as client, pytest.raises(kaos_identity.AccessDenied) as exc:
        client.get("http://downstream/data")
    assert exc.value.decision.reason == "platform_grant_missing"
    assert exc.value.decision.resource == "downstream"


@respx.mock
@pytest.mark.asyncio
async def test_async_send_raises_reauth_on_ext_proc():
    respx.post("http://downstream/tool").respond(
        200,
        headers={
            "x-kaos-access-reason": "third_party_reauth_required",
            "x-kaos-reauth-url": "https://idp.example/reauth",
        },
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(kaos_identity.ReauthenticationRequired) as exc:
            await client.post("http://downstream/tool")
    assert exc.value.reauth_url == "https://idp.example/reauth"


@respx.mock
def test_sync_send_normal_response_unaffected():
    respx.get("http://downstream/ok").respond(200, json={"ok": True})
    with httpx.Client() as client:
        resp = client.get("http://downstream/ok")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@respx.mock
def test_sync_send_non_kaos_403_not_raised():
    respx.get("http://downstream/forbidden").respond(403, json={"error": "nope"})
    with httpx.Client() as client:
        resp = client.get("http://downstream/forbidden")
    assert resp.status_code == 403
