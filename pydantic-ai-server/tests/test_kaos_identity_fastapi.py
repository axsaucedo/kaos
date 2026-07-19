"""Unit tests for kaos_identity.instrument_fastapi inbound boundary instrumentation."""

import kaos_identity
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(**kwargs):
    app = FastAPI()
    kaos_identity.instrument_fastapi(app, **kwargs)

    @app.get("/seen")
    async def seen():
        # The context set by the middleware must be visible inside the endpoint
        # (same task — pure ASGI middleware, not BaseHTTPMiddleware).
        return kaos_identity.current()

    return TestClient(app)


def test_generates_request_id_when_absent():
    client = _make_app(actor="kaos://agent/default/a")
    seen = client.get("/seen").json()
    assert seen["request_id"].startswith("req-")
    assert seen["actor"] == "kaos://agent/default/a"


def test_propagates_inbound_subject_and_request_id():
    client = _make_app(actor="kaos://agent/default/a")
    seen = client.get(
        "/seen",
        headers={
            "x-request-id": "req-fixed",
            "x-principal": "keycloak://kaos/alice",
            "authorization": "Bearer user-token",
            "x-aib-scopes": "read",
        },
    ).json()
    assert seen["request_id"] == "req-fixed"
    assert seen["principal"] == "keycloak://kaos/alice"
    assert seen["subject_token"] == "user-token"  # Bearer stripped on the way in
    assert seen["scopes"] == "read"


def test_local_actor_overrides_inbound_actor():
    """The actor is always THIS agent — never the inbound caller's actor."""
    client = _make_app(actor="kaos://agent/default/B", actor_token="b-token")
    seen = client.get(
        "/seen",
        headers={
            "x-actor": "kaos://agent/default/A",
            "x-agent-authorization": "Bearer a-token",
        },
    ).json()
    assert seen["actor"] == "kaos://agent/default/B"
    assert seen["actor_token"] == "b-token"


def test_session_from_legacy_header():
    client = _make_app(actor="kaos://agent/default/a")
    seen = client.get("/seen", headers={"x-session-id": "sess-legacy"}).json()
    assert seen["session_id"] == "sess-legacy"


def test_principal_resolver_used_when_no_inbound_principal():
    client = _make_app(
        actor="kaos://agent/default/a",
        principal_resolver=lambda headers: "resolved://user",
    )
    seen = client.get("/seen").json()
    assert seen["principal"] == "resolved://user"


def test_verified_principal_resolver_overrides_inbound_principal():
    client = _make_app(
        actor="kaos://agent/default/a",
        principal_resolver=lambda headers: headers.get("x-verified-sub"),
    )
    seen = client.get(
        "/seen",
        headers={"x-principal": "spoofed-user", "x-verified-sub": "verified-user"},
    ).json()
    assert seen["principal"] == "verified-user"


def test_env_defaults_used(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_IDENTITY", "kaos://agent/default/env")
    monkeypatch.setenv("AGENT_AUTH_TOKEN", "env-token")
    monkeypatch.setenv("AGENT_AUTH_PRINCIPAL", "service://env")
    client = _make_app()
    seen = client.get("/seen").json()
    assert seen["actor"] == "kaos://agent/default/env"
    assert seen["actor_token"] == "env-token"
    assert seen["principal"] == "service://env"


def test_context_reset_between_requests():
    client = _make_app(actor="kaos://agent/default/a")
    client.get("/seen", headers={"x-principal": "keycloak://kaos/alice"})
    # A subsequent request without a principal must not leak the previous one.
    seen = client.get("/seen").json()
    assert "principal" not in seen
