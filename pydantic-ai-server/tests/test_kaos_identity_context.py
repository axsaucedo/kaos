"""Unit tests for request-local identity context and header serialization."""

import asyncio

import kaos_identity
from kaos_identity.instrument import _as_bearer, _build_context


def _clear():
    kaos_identity.ctx.replace({})


def test_to_headers_maps_fields_to_headers():
    _clear()
    kaos_identity.ctx.update(
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
    headers = kaos_identity.ctx.to_headers()
    assert headers["x-request-id"] == "req-1"
    assert headers["x-aib-session-id"] == "sess-1"
    assert headers["x-principal"] == "keycloak://kaos/alice"
    assert headers["x-actor"] == "kaos://agent/default/researcher"
    assert headers["x-aib-scopes"] == "read write"
    assert headers["authorization"] == "Bearer user-token"
    assert headers["x-agent-authorization"] == "Bearer actor-token"


def test_to_headers_omits_empty_fields():
    _clear()
    kaos_identity.ctx["request_id"] = "req-only"
    headers = kaos_identity.ctx.to_headers()
    assert headers == {"x-request-id": "req-only"}


def test_bearer_wrapping_is_idempotent():
    assert _as_bearer("abc") == "Bearer abc"
    assert _as_bearer("Bearer abc") == "Bearer abc"
    assert _as_bearer("bearer abc") == "bearer abc"


def test_token_already_bearer_not_double_wrapped():
    _clear()
    kaos_identity.ctx["subject_token"] = "Bearer existing"
    assert kaos_identity.ctx.to_headers()["authorization"] == "Bearer existing"


def test_mapping_operations():
    _clear()
    kaos_identity.ctx.update({"actor": "a", "principal": "p"})
    assert kaos_identity.ctx.get("actor") == "a"
    assert kaos_identity.ctx.get("missing") is None
    kaos_identity.ctx.pop("actor", None)
    assert "actor" not in kaos_identity.ctx
    assert kaos_identity.ctx["principal"] == "p"
    assert len(kaos_identity.ctx) == 1


def test_replace_and_reset_round_trip():
    _clear()
    kaos_identity.ctx["actor"] = "first"
    token = kaos_identity.ctx.replace({"actor": "second"})
    assert kaos_identity.ctx["actor"] == "second"
    kaos_identity.ctx.reset(token)
    assert kaos_identity.ctx["actor"] == "first"


def test_current_returns_copy():
    _clear()
    kaos_identity.ctx["actor"] = "a"
    snapshot = kaos_identity.current()
    snapshot["actor"] = "mutated"
    assert kaos_identity.ctx["actor"] == "a"


def test_build_context_drops_empty():
    built = _build_context(request_id="r", actor="a", principal=None, scopes="")
    assert built == {"request_id": "r", "actor": "a"}


def test_contextvar_isolation_across_tasks():
    """Each asyncio task gets its own copy-on-write context — no cross-talk."""
    _clear()
    kaos_identity.ctx["actor"] = "root"
    seen = {}

    async def worker(name):
        kaos_identity.ctx["actor"] = name
        await asyncio.sleep(0)
        seen[name] = kaos_identity.ctx["actor"]

    async def main():
        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(main())
    assert seen == {"a": "a", "b": "b"}
    # Mutations inside tasks do not leak back into the parent context.
    assert kaos_identity.ctx["actor"] == "root"
