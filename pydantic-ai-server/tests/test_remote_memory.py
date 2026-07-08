"""Tests for the service-backed memory client.

Drive ``RemoteMemory`` against a stub of the central memory service using an
``httpx.MockTransport`` so the client is exercised end to end (routes, payloads,
response parsing) without a running service, and verify its best-effort
semantics: recall degrades to empty on failure, write/forget fail soft by
default and raise under strict, and degraded responses never raise.
"""

import httpx
import pytest

from pais.memory import MemoryScope, RecalledMemory, ScopeLevel, RemoteMemory


def _client(handler) -> RemoteMemory:
    transport = httpx.MockTransport(handler)
    return RemoteMemory("http://memory.test:8080", client=httpx.AsyncClient(transport=transport))


def _scope() -> MemoryScope:
    return MemoryScope(
        level=ScopeLevel.SESSION,
        principal="alice",
        agent_client_id="agent-1",
        session_id="sess-1",
    )


class TestRecall:
    @pytest.mark.asyncio
    async def test_recall_calls_route_and_parses_response(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            import json

            body = json.loads(request.content)
            seen["payload"] = body
            return httpx.Response(
                200,
                json={
                    "facts": [{"memory": "alice likes tea", "score": 0.9}],
                    "short_term": {
                        "recent": [["user", "hi"], ["assistant", "hello"]],
                    },
                    "medium_term": {
                        "summary": "prior chat",
                    },
                    "block": "## Relevant memory\nalice likes tea",
                    "degraded": False,
                },
            )

        mem = _client(handler)
        recalled = await mem.recall(_scope(), "tea", top_k=5, token_budget=512)

        assert seen["url"].endswith("/v1/recall")
        assert seen["payload"]["query"] == "tea"
        assert seen["payload"]["top_k"] == 5
        assert seen["payload"]["short_term_token_budget"] == 512
        assert seen["payload"]["scope"]["level"] == "session"
        assert isinstance(recalled, RecalledMemory)
        assert recalled.facts[0]["memory"] == "alice likes tea"
        assert recalled.summary == "prior chat"
        assert recalled.recent == [("user", "hi"), ("assistant", "hello")]
        assert recalled.block.startswith("## Relevant memory")
        assert recalled.degraded is False
        await mem.close()

    @pytest.mark.asyncio
    async def test_recall_degrades_to_empty_on_transport_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("service down")

        mem = _client(handler)
        recalled = await mem.recall(_scope(), "tea")
        assert recalled.is_empty
        assert recalled.degraded is True
        await mem.close()

    @pytest.mark.asyncio
    async def test_recall_degrades_on_5xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "not ready"})

        mem = _client(handler)
        recalled = await mem.recall(_scope(), "tea")
        assert recalled.degraded is True
        await mem.close()

    @pytest.mark.asyncio
    async def test_recall_passes_through_service_degraded_flag(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "facts": [],
                    "short_term": {"recent": [["user", "hi"]]},
                    "medium_term": {"summary": ""},
                    "block": "## Recent turns\nuser: hi",
                    "degraded": True,
                },
            )

        mem = _client(handler)
        recalled = await mem.recall(_scope(), "tea")
        assert recalled.degraded is True
        assert recalled.recent == [("user", "hi")]
        await mem.close()


class TestWrite:
    @pytest.mark.asyncio
    async def test_write_posts_route_and_returns_accepted(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen["url"] = str(request.url)
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                202, json={"accepted": True, "scheduled": True, "degraded": False}
            )

        mem = _client(handler)
        ok = await mem.write(_scope(), [("user", "remember the sky is blue")], infer=True)
        assert ok is True
        assert seen["url"].endswith("/v1/write")
        assert seen["payload"]["turns"] == [{"role": "user", "content": "remember the sky is blue"}]
        assert seen["payload"]["infer"] is True
        assert "failure_mode" not in seen["payload"]
        await mem.close()

    @pytest.mark.asyncio
    async def test_write_includes_explicit_failure_mode(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                202, json={"accepted": True, "scheduled": True, "degraded": False}
            )

        mem = _client(handler)
        await mem.write(_scope(), [("user", "x")], failure_mode="soft")
        assert seen["payload"]["failure_mode"] == "soft"
        await mem.close()

    @pytest.mark.asyncio
    async def test_write_fails_soft_on_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("service down")

        mem = _client(handler)
        ok = await mem.write(_scope(), [("user", "x")])
        assert ok is False
        await mem.close()

    @pytest.mark.asyncio
    async def test_write_raises_under_strict(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("service down")

        mem = _client(handler)
        with pytest.raises(httpx.ConnectError):
            await mem.write(_scope(), [("user", "x")], failure_mode="strict")
        await mem.close()


class TestForget:
    @pytest.mark.asyncio
    async def test_forget_posts_route(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"forgotten": True, "degraded": False})

        mem = _client(handler)
        ok = await mem.forget(_scope())
        assert ok is True
        assert seen["url"].endswith("/v1/forget")
        await mem.close()

    @pytest.mark.asyncio
    async def test_forget_fails_soft_on_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        mem = _client(handler)
        ok = await mem.forget(_scope())
        assert ok is False
        await mem.close()


class TestLegacyMethodsAreNoop:
    @pytest.mark.asyncio
    async def test_session_methods_do_not_hold_state(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        mem = _client(handler)
        sid = await mem.get_or_create_session("sess-9")
        assert sid == "sess-9"
        assert await mem.add_event("sess-9", "user_message", "hi") is True
        assert await mem.get_session_events("sess-9") == []
        assert await mem.list_sessions() == []
        await mem.close()

    def test_requires_endpoint(self):
        with pytest.raises(ValueError):
            RemoteMemory("")
