"""Unit tests for the aib request-local context and header serialization."""

import asyncio

import aib
from aib.instrument import _as_bearer, _build_context


def _clear():
    aib.ctx.replace({})


def test_to_headers_maps_fields_to_headers():
    _clear()
    aib.ctx.update(
        {
            "request_id": "req-1",
            "session_id": "sess-1",
            "principal": "keycloak://kaos/alice",
            "subject_token": "user-token",
            "actor": "kaos://agent/default/researcher",
            "actor_token": "actor-token",
            "scopes": "read write",
        }
    )
    headers = aib.ctx.to_headers()
    assert headers["x-request-id"] == "req-1"
    assert headers["x-aib-session-id"] == "sess-1"
    assert headers["x-principal"] == "keycloak://kaos/alice"
    assert headers["x-actor"] == "kaos://agent/default/researcher"
    assert headers["x-aib-scopes"] == "read write"
    assert headers["authorization"] == "Bearer user-token"
    assert headers["x-agent-authorization"] == "Bearer actor-token"


def test_to_headers_omits_empty_fields():
    _clear()
    aib.ctx["request_id"] = "req-only"
    headers = aib.ctx.to_headers()
    assert headers == {"x-request-id": "req-only"}


def test_bearer_wrapping_is_idempotent():
    assert _as_bearer("abc") == "Bearer abc"
    assert _as_bearer("Bearer abc") == "Bearer abc"
    assert _as_bearer("bearer abc") == "bearer abc"


def test_token_already_bearer_not_double_wrapped():
    _clear()
    aib.ctx["subject_token"] = "Bearer existing"
    assert aib.ctx.to_headers()["authorization"] == "Bearer existing"


def test_mapping_operations():
    _clear()
    aib.ctx.update({"actor": "a", "principal": "p"})
    assert aib.ctx.get("actor") == "a"
    assert aib.ctx.get("missing") is None
    aib.ctx.pop("actor", None)
    assert "actor" not in aib.ctx
    assert aib.ctx["principal"] == "p"
    assert len(aib.ctx) == 1


def test_replace_and_reset_round_trip():
    _clear()
    aib.ctx["actor"] = "first"
    token = aib.ctx.replace({"actor": "second"})
    assert aib.ctx["actor"] == "second"
    aib.ctx.reset(token)
    assert aib.ctx["actor"] == "first"


def test_current_returns_copy():
    _clear()
    aib.ctx["actor"] = "a"
    snapshot = aib.current()
    snapshot["actor"] = "mutated"
    assert aib.ctx["actor"] == "a"


def test_build_context_drops_empty():
    built = _build_context(request_id="r", actor="a", principal=None, scopes="")
    assert built == {"request_id": "r", "actor": "a"}


def test_contextvar_isolation_across_tasks():
    """Each asyncio task gets its own copy-on-write context — no cross-talk."""
    _clear()
    aib.ctx["actor"] = "root"
    seen = {}

    async def worker(name):
        aib.ctx["actor"] = name
        await asyncio.sleep(0)
        seen[name] = aib.ctx["actor"]

    async def main():
        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(main())
    assert seen == {"a": "a", "b": "b"}
    # Mutations inside tasks do not leak back into the parent context.
    assert aib.ctx["actor"] == "root"
