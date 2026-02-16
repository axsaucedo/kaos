"""
Unit tests for RedisMemory.

Uses fakeredis to test without a real Redis server.
"""

import pytest
import logging

from agent.memory import RedisMemory, MemoryEvent

logger = logging.getLogger(__name__)


@pytest.fixture
def redis_memory(monkeypatch):
    """Create a RedisMemory backed by fakeredis for testing."""
    import fakeredis.aioredis

    mem = RedisMemory.__new__(RedisMemory)
    mem._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mem.max_sessions = 1000
    mem.max_events_per_session = 500
    mem._prefix = "kaos:sessions"
    return mem


class TestRedisMemory:
    """Tests for RedisMemory (mirrors LocalMemory tests)."""

    @pytest.mark.asyncio
    async def test_create_and_get_session(self, redis_memory):
        sid = await redis_memory.create_session("test_app", "test_user")
        assert sid is not None

        session = await redis_memory.get_session(sid)
        assert session is not None
        assert session.user_id == "test_user"
        assert session.app_name == "test_app"

    @pytest.mark.asyncio
    async def test_list_sessions(self, redis_memory):
        s1 = await redis_memory.create_session("app", "user1")
        s2 = await redis_memory.create_session("app", "user2")

        all_sessions = await redis_memory.list_sessions()
        assert s1 in all_sessions
        assert s2 in all_sessions

        user1_sessions = await redis_memory.list_sessions(user_id="user1")
        assert s1 in user1_sessions
        assert s2 not in user1_sessions

    @pytest.mark.asyncio
    async def test_add_and_get_events(self, redis_memory):
        sid = await redis_memory.create_session("app", "user")

        event = redis_memory.create_event("user_message", "Hello!")
        added = await redis_memory.add_event(sid, event)
        assert added is True

        events = await redis_memory.get_session_events(sid)
        assert len(events) == 1
        assert events[0].event_type == "user_message"
        assert events[0].content == "Hello!"

    @pytest.mark.asyncio
    async def test_add_event_shorthand(self, redis_memory):
        sid = await redis_memory.create_session("app", "user")
        await redis_memory.add_event(sid, "agent_response", "Hi there!")

        events = await redis_memory.get_session_events(sid)
        assert len(events) == 1
        assert events[0].content == "Hi there!"

    @pytest.mark.asyncio
    async def test_add_event_missing_session(self, redis_memory):
        result = await redis_memory.add_event("nonexistent", "user_message", "Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_build_conversation_context(self, redis_memory):
        sid = await redis_memory.create_session("app", "user")
        await redis_memory.add_event(sid, "user_message", "What is 2+2?")
        await redis_memory.add_event(sid, "agent_response", "4")
        await redis_memory.add_event(sid, "tool_call", {"tool": "calc"})

        ctx = await redis_memory.build_conversation_context(sid)
        assert "What is 2+2?" in ctx
        assert "4" in ctx
        # tool_call events should not appear in conversation context
        assert "calc" not in ctx

    @pytest.mark.asyncio
    async def test_event_eviction(self, redis_memory):
        redis_memory.max_events_per_session = 5
        sid = await redis_memory.create_session("app", "user")

        for i in range(7):
            await redis_memory.add_event(sid, "user_message", f"Message {i}")

        events = await redis_memory.get_session_events(sid)
        assert len(events) == 5
        contents = [e.content for e in events]
        assert "Message 2" in contents
        assert "Message 6" in contents
        assert "Message 0" not in contents

    @pytest.mark.asyncio
    async def test_delete_session(self, redis_memory):
        sid = await redis_memory.create_session("app", "user")
        await redis_memory.add_event(sid, "user_message", "Hello")

        deleted = await redis_memory.delete_session(sid)
        assert deleted is True

        session = await redis_memory.get_session(sid)
        assert session is None

        deleted_again = await redis_memory.delete_session(sid)
        assert deleted_again is False

    @pytest.mark.asyncio
    async def test_get_or_create_session(self, redis_memory):
        sid = await redis_memory.get_or_create_session("custom-id")
        assert sid == "custom-id"

        session = await redis_memory.get_session("custom-id")
        assert session is not None

        # Calling again should not overwrite
        await redis_memory.add_event("custom-id", "user_message", "test")
        sid2 = await redis_memory.get_or_create_session("custom-id")
        assert sid2 == "custom-id"
        events = await redis_memory.get_session_events("custom-id")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_memory_stats(self, redis_memory):
        sid = await redis_memory.create_session("app", "user")
        await redis_memory.add_event(sid, "user_message", "Hello")
        await redis_memory.add_event(sid, "agent_response", "Hi")

        stats = await redis_memory.get_memory_stats()
        assert stats["total_sessions"] == 1
        assert stats["total_events"] == 2

    @pytest.mark.asyncio
    async def test_filter_events_by_type(self, redis_memory):
        sid = await redis_memory.create_session("app", "user")
        await redis_memory.add_event(sid, "user_message", "Hello")
        await redis_memory.add_event(sid, "tool_call", "calc")
        await redis_memory.add_event(sid, "agent_response", "Done")

        user_events = await redis_memory.get_session_events(sid, ["user_message"])
        assert len(user_events) == 1
        assert user_events[0].content == "Hello"

        logger.info("✓ RedisMemory tests passed")
