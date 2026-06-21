"""Wiring tests: the aib SDK is active inside the pais AgentServer."""

import aib
import pytest
from aib.instrument import _PropagationMiddleware
from fastapi.testclient import TestClient
from pais.serverutils import AgentServerSettings
from pais.server import create_agent_server


def _settings(**overrides):
    base = dict(
        agent_name="researcher",
        model_api_url="http://model.local",
        model_name="test-model",
        agent_log_level="WARNING",
    )
    base.update(overrides)
    return AgentServerSettings.model_validate(base)


def _propagation_middleware(app):
    for mw in app.user_middleware:
        if mw.cls is _PropagationMiddleware:
            return mw
    return None


def test_server_wires_fastapi_and_httpx_instrumentation():
    server = create_agent_server(_settings())
    mw = _propagation_middleware(server.app)
    assert mw is not None
    # Default local actor derives from the agent name.
    assert mw.kwargs["actor"] == "kaos://agent/researcher"
    assert aib.instrument._httpx_patched is True


def test_security_actor_setting_overrides_default():
    server = create_agent_server(_settings(security_actor="kaos://agent/custom/id"))
    mw = _propagation_middleware(server.app)
    assert mw.kwargs["actor"] == "kaos://agent/custom/id"


def test_request_through_server_runs_middleware_and_resets():
    server = create_agent_server(_settings())
    aib.ctx.replace({})
    client = TestClient(server.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    # Context is request-scoped and reset afterwards — no leak into the process.
    assert aib.current() == {}


def test_security_context_excludes_raw_tokens():
    aib.ctx.replace(
        {
            "request_id": "req-1",
            "principal": "keycloak://kaos/alice",
            "actor": "kaos://agent/researcher",
            "subject_token": "user-token",
            "actor_token": "actor-token",
        }
    )
    sc = aib.security_context()
    assert sc == {
        "request_id": "req-1",
        "principal": "keycloak://kaos/alice",
        "actor": "kaos://agent/researcher",
    }
    assert "subject_token" not in sc
    assert "actor_token" not in sc
    aib.ctx.replace({})


@pytest.mark.asyncio
async def test_agent_deps_carry_non_secret_security_context():
    """AgentDeps built during a run carry the non-secret context, never tokens."""
    server = create_agent_server(_settings())
    aib.ctx.replace(
        {
            "request_id": "req-x",
            "actor": "kaos://agent/researcher",
            "subject_token": "secret",
        }
    )
    _prompt, _history, deps, _limits = await server._prepare_run("hello", "sess-1")
    assert deps.security_context == {
        "request_id": "req-x",
        "actor": "kaos://agent/researcher",
    }
    aib.ctx.replace({})
