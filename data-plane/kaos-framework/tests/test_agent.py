"""
Consolidated Agent tests.

Tests Agent, RemoteAgent, AgentCard, LocalMemory, NullMemory, and ModelAPI functionality.
Focuses on meaningful integration between components.
"""

import pytest
import logging
from unittest.mock import Mock, AsyncMock
from typing import List, Dict, Optional

from agent.client import Agent, RemoteAgent, AgentCard
from agent.memory import LocalMemory, NullMemory, RedisMemory
from agent.server import AgentServer
from modelapi.client import ModelAPI, ModelResponse, LiteLLM

logger = logging.getLogger(__name__)


class MockModelAPI(ModelAPI):
    """Mock ModelAPI for testing."""

    def __init__(self, name: str = "mock"):
        self.name = name
        self.call_count = 0
        self.model = "mock"
        self.api_base = "mock://localhost"
        self._mock_responses_template: Optional[List[str]] = None  # Not used in this mock

    def reset_mock_responses(self) -> None:
        """No-op for this mock - it generates responses dynamically."""
        pass

    @property
    def has_mock_responses(self) -> bool:
        """This mock doesn't use template-based responses."""
        return False

    async def process_message(
        self, messages: List[Dict], stream: bool = False, seed: Optional[int] = None, tools=None
    ):
        """Return a mock response based on the name.

        Returns ModelResponse if stream=False, AsyncIterator[str] if stream=True.
        """
        self.call_count += 1
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        content = f"[{self.name}] Response to: {user_msg}"
        if stream:
            return self._yield_content(content)
        return ModelResponse(content=content, finish_reason="stop")

    async def _yield_content(self, content: str):
        """Yield content as streaming chunks."""
        for word in content.split():
            yield word + " "

    async def close(self):
        pass


class TestAgentCreationAndCard:
    """Tests for Agent creation and AgentCard generation."""

    @pytest.mark.asyncio
    async def test_agent_creation_and_card_generation(self):
        """Test Agent can be created and generates valid AgentCard."""
        mock_llm = MockModelAPI("test-agent")
        memory = LocalMemory()

        # Create agent with minimal config
        agent = Agent(
            name="test-agent",
            description="Test Agent Description",
            instructions="You are a test assistant.",
            model_api=mock_llm,
            memory=memory,
        )

        assert agent.name == "test-agent"
        assert agent.description == "Test Agent Description"
        assert agent.model_api == mock_llm
        assert agent.memory == memory

        # Test AgentCard generation (now async to init MCP clients)
        card = await agent.get_agent_card("http://localhost:8000")

        assert card.name == "test-agent"
        assert card.description == "Test Agent Description"
        assert card.url == "http://localhost:8000"
        assert "message_processing" in card.capabilities
        assert "task_execution" in card.capabilities

        # Test card serialization
        card_dict = card.to_dict()
        assert "name" in card_dict
        assert "description" in card_dict
        assert "url" in card_dict
        assert "skills" in card_dict
        assert "capabilities" in card_dict

        logger.info("✓ Agent creation and card generation work correctly")

    @pytest.mark.asyncio
    async def test_agent_with_sub_agents(self):
        """Test Agent with sub-agents has delegation capability and dict access."""
        mock_llm = MockModelAPI("coordinator")

        # Create sub-agents
        sub_agent1 = RemoteAgent(name="worker-1", card_url="http://localhost:8001")
        sub_agent2 = RemoteAgent(name="worker-2", card_url="http://localhost:8002")

        agent = Agent(name="coordinator", model_api=mock_llm, sub_agents=[sub_agent1, sub_agent2])

        # Verify sub_agents is a dict with O(1) access
        assert isinstance(agent.sub_agents, dict)
        assert len(agent.sub_agents) == 2
        assert "worker-1" in agent.sub_agents
        assert "worker-2" in agent.sub_agents
        assert agent.sub_agents["worker-1"] is sub_agent1
        assert agent.sub_agents["worker-2"] is sub_agent2

        # Card should indicate delegation capability (now async)
        card = await agent.get_agent_card("http://localhost:8000")
        assert "task_delegation" in card.capabilities

        # Cleanup
        await sub_agent1.close()
        await sub_agent2.close()

        logger.info("✓ Agent with sub-agents works correctly (dict access)")


class TestMemorySystem:
    """Tests for LocalMemory functionality."""

    @pytest.mark.asyncio
    async def test_memory_system_complete_workflow(self):
        """Test complete memory workflow: sessions, events, context."""
        memory = LocalMemory()

        # Create session
        session_id = await memory.create_session("test_app", "test_user")
        assert session_id is not None

        # List sessions
        sessions = await memory.list_sessions()
        assert session_id in sessions

        # Create and add events
        event1 = memory.create_event("user_message", "Hello agent!")
        event2 = memory.create_event("agent_response", "Hello user!")
        event3 = memory.create_event("tool_call", {"tool": "calculator", "args": {"a": 1}})

        await memory.add_event(session_id, event1)
        await memory.add_event(session_id, event2)
        await memory.add_event(session_id, event3)

        # Get events
        events = await memory.get_session_events(session_id)
        assert len(events) == 3
        assert events[0].event_type == "user_message"
        assert events[0].content == "Hello agent!"
        assert events[1].event_type == "agent_response"
        assert events[2].event_type == "tool_call"

        # Build context
        context = await memory.build_conversation_context(session_id)
        assert "Hello agent!" in context
        assert "Hello user!" in context

        logger.info("✓ Memory system complete workflow works correctly")

    @pytest.mark.asyncio
    async def test_deque_based_event_storage_auto_eviction(self):
        """Test that deque-based storage automatically evicts old events."""
        memory = LocalMemory(max_sessions=10, max_events_per_session=5)

        session_id = await memory.create_session("test_app", "test_user")

        # Add 7 events (exceeds max_events_per_session=5)
        for i in range(7):
            event = memory.create_event("user_message", f"Message {i}")
            await memory.add_event(session_id, event)

        # Should only have 5 events (oldest evicted automatically by deque)
        events = await memory.get_session_events(session_id)
        assert len(events) == 5

        # Should have messages 2-6 (0 and 1 were evicted)
        contents = [e.content for e in events]
        assert "Message 2" in contents
        assert "Message 6" in contents
        assert "Message 0" not in contents
        assert "Message 1" not in contents

        logger.info("✓ Deque-based event storage auto-eviction works correctly")


class TestNullMemory:
    """Tests for NullMemory (disabled memory) functionality."""

    @pytest.mark.asyncio
    async def test_null_memory_all_operations_succeed(self):
        """Test NullMemory operations all succeed silently."""
        memory = NullMemory()

        # Create session returns constant ID or provided ID
        session_id = await memory.create_session("app", "user")
        assert session_id == "null-session"

        custom_session = await memory.create_session("app", "user", "custom-id")
        assert custom_session == "custom-id"

        # Get or create returns the provided ID
        session = await memory.get_or_create_session("my-session")
        assert session == "my-session"

        # Get session returns None
        assert await memory.get_session("any-id") is None

        # Create event returns a valid event
        event = memory.create_event("user_message", "Hello")
        assert event is not None
        assert event.event_type == "user_message"
        assert event.content == "Hello"

        # Add event succeeds
        result = await memory.add_event("any-session", event)
        assert result is True

        # Get session events returns empty list
        events = await memory.get_session_events("any-session")
        assert events == []

        # Build context returns empty string
        context = await memory.build_conversation_context("any-session")
        assert context == ""

        # List sessions returns empty list
        sessions = await memory.list_sessions()
        assert sessions == []

        # Delete session returns True
        deleted = await memory.delete_session("any-session")
        assert deleted is True

        # Get memory stats returns zeros
        stats = await memory.get_memory_stats()
        assert stats["total_sessions"] == 0
        assert stats["total_events"] == 0

        # Cleanup returns 0
        cleaned = await memory.cleanup_old_sessions()
        assert cleaned == 0

        logger.info("✓ NullMemory all operations succeed silently")

    @pytest.mark.asyncio
    async def test_agent_with_null_memory_processes_messages(self):
        """Test Agent works correctly with NullMemory."""
        mock_llm = MockModelAPI("null-memory-agent")
        null_memory = NullMemory()

        agent = Agent(
            name="null-memory-agent",
            instructions="Test agent with disabled memory.",
            model_api=mock_llm,
            memory=null_memory,
            memory_enabled=False,
        )

        # Process a message - should work without storing events
        response_chunks = []
        async for chunk in agent.process_message("Hello!"):
            response_chunks.append(chunk)

        response = "".join(response_chunks)
        assert len(response) > 0

        # Memory should still be empty
        sessions = await null_memory.list_sessions()
        assert sessions == []

        logger.info("✓ Agent with NullMemory processes messages correctly")


class TestRedisMemory:
    """Tests for RedisMemory verifying actual Redis commands issued."""

    def _make_redis_memory(self, mock_redis):
        """Create a RedisMemory with a mocked Redis client."""
        from unittest.mock import patch

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            return RedisMemory(redis_url="redis://localhost:6379", max_events_per_session=10)

    @pytest.mark.asyncio
    async def test_create_session_issues_hset_and_zadd(self):
        """Verify create_session pipelines HSET (session data) + EXPIRE + ZADD (index)."""
        from unittest.mock import AsyncMock, MagicMock

        mock_redis = AsyncMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.zcard = AsyncMock(return_value=0)

        memory = self._make_redis_memory(mock_redis)
        sid = await memory.create_session("app", "user1", "s1")
        assert sid == "s1"

        # Pipeline must contain: hset, expire, zadd
        mock_pipe.hset.assert_called_once()
        call_args = mock_pipe.hset.call_args
        assert call_args[0][0] == "kaos:memory:session:s1"
        mapping = call_args[1]["mapping"]
        assert mapping["session_id"] == "s1"
        assert mapping["user_id"] == "user1"

        mock_pipe.expire.assert_called_once()
        mock_pipe.zadd.assert_called_once()
        mock_pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_event_uses_rpush_and_ltrim(self):
        """Verify add_event uses RPUSH + LTRIM (list-based) in a single pipeline."""
        import json
        from unittest.mock import AsyncMock, MagicMock

        mock_redis = AsyncMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.exists = AsyncMock(return_value=True)

        memory = self._make_redis_memory(mock_redis)
        result = await memory.add_event("s1", "user_message", "Hello!")
        assert result is True

        # Verify RPUSH with JSON event data
        mock_pipe.rpush.assert_called_once()
        rpush_args = mock_pipe.rpush.call_args[0]
        assert rpush_args[0] == "kaos:memory:events:s1"
        event_data = json.loads(rpush_args[1])
        assert event_data["event_type"] == "user_message"
        assert event_data["content"] == "Hello!"
        assert "event_id" in event_data

        # Verify LTRIM for cap enforcement (keep last N)
        mock_pipe.ltrim.assert_called_once_with("kaos:memory:events:s1", -10, -1)

        # Verify session update + index + TTL refresh
        mock_pipe.hset.assert_called_once()
        mock_pipe.zadd.assert_called_once()
        assert mock_pipe.expire.call_count == 2  # session key + events key

    @pytest.mark.asyncio
    async def test_get_events_uses_lrange_and_skips_malformed(self):
        """Verify _get_raw_events uses LRANGE and skips malformed entries."""
        import json
        from unittest.mock import AsyncMock

        valid_event = json.dumps(
            {
                "event_id": "e1",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "event_type": "user_message",
                "content": "hi",
                "metadata": {},
            }
        )
        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[valid_event, "not-json", "{}"])

        memory = self._make_redis_memory(mock_redis)
        events = await memory._get_raw_events("s1")

        mock_redis.lrange.assert_called_once_with("kaos:memory:events:s1", 0, -1)
        assert len(events) == 1
        assert events[0].event_type == "user_message"

    @pytest.mark.asyncio
    async def test_get_events_deduplicates_by_event_id(self):
        """Verify duplicate event_ids are skipped on read."""
        import json
        from unittest.mock import AsyncMock

        event = {
            "event_id": "e1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "event_type": "user_message",
            "content": "hi",
            "metadata": {},
        }
        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[json.dumps(event), json.dumps(event)])

        memory = self._make_redis_memory(mock_redis)
        events = await memory._get_raw_events("s1")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_add_event_rejects_missing_session(self):
        """Verify add_event returns False for non-existent sessions."""
        from unittest.mock import AsyncMock

        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)

        memory = self._make_redis_memory(mock_redis)
        result = await memory.add_event("nonexistent", "user_message", "Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        """Verify close() shuts down the Redis connection."""
        from unittest.mock import AsyncMock

        mock_redis = AsyncMock()
        memory = self._make_redis_memory(mock_redis)
        await memory.close()
        mock_redis.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_memory_stats_uses_llen(self):
        """Verify stats use LLEN (list length) instead of ZCARD (sorted set)."""
        from unittest.mock import AsyncMock

        mock_redis = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=2)
        mock_redis.zrange = AsyncMock(return_value=["s1", "s2"])
        mock_redis.llen = AsyncMock(return_value=5)

        memory = self._make_redis_memory(mock_redis)
        stats = await memory.get_memory_stats()

        assert stats["total_sessions"] == 2
        assert stats["total_events"] == 10  # 5 per session * 2
        assert mock_redis.llen.call_count == 2


class TestMessageProcessing:
    """Tests for Agent message processing with memory."""

    @pytest.mark.asyncio
    async def test_message_processing_creates_memory_events(self):
        """Test that message processing creates appropriate memory events."""
        mock_llm = MockModelAPI("processor")
        memory = LocalMemory()

        agent = Agent(
            name="processor",
            instructions="Process messages.",
            model_api=mock_llm,
            memory=memory,
        )

        # Process a message
        response_chunks = []
        async for chunk in agent.process_message("Hello, process this!"):
            response_chunks.append(chunk)

        response = "".join(response_chunks)
        assert len(response) > 0
        assert "processor" in response.lower()

        # Verify memory events were created
        sessions = await memory.list_sessions()
        assert len(sessions) >= 1

        session_id = sessions[-1]
        events = await memory.get_session_events(session_id)

        # Should have user_message and agent_response
        event_types = [e.event_type for e in events]
        assert "user_message" in event_types
        assert "agent_response" in event_types

        # Verify content
        user_event = next(e for e in events if e.event_type == "user_message")
        assert "Hello, process this!" in user_event.content

        # Verify model was called
        assert mock_llm.call_count >= 1

        logger.info("✓ Message processing with memory works correctly")

    @pytest.mark.asyncio
    async def test_message_processing_with_provided_session_id(self):
        """Test that providing a session_id correctly stores events in that session."""
        mock_llm = MockModelAPI("session-test")
        memory = LocalMemory()

        agent = Agent(
            name="session-agent",
            instructions="Test session handling.",
            model_api=mock_llm,
            memory=memory,
        )

        # Use a specific session ID
        custom_session_id = "my-custom-session-123"

        # Process first message with custom session ID
        response_chunks = []
        async for chunk in agent.process_message("First message", session_id=custom_session_id):
            response_chunks.append(chunk)

        response1 = "".join(response_chunks)
        assert len(response1) > 0

        # Process second message with same session ID
        response_chunks = []
        async for chunk in agent.process_message("Second message", session_id=custom_session_id):
            response_chunks.append(chunk)

        response2 = "".join(response_chunks)
        assert len(response2) > 0

        # Verify session exists with our custom ID
        sessions = await memory.list_sessions()
        assert custom_session_id in sessions, f"Custom session ID not found. Sessions: {sessions}"

        # Get events from that specific session
        events = await memory.get_session_events(custom_session_id)

        # Should have 2 user_messages and 2 agent_responses (one for each message)
        event_types = [e.event_type for e in events]
        user_message_count = event_types.count("user_message")
        agent_response_count = event_types.count("agent_response")

        assert user_message_count == 2, f"Expected 2 user_messages, got {user_message_count}"
        assert agent_response_count == 2, f"Expected 2 agent_responses, got {agent_response_count}"

        # Verify both messages are in the events
        user_events = [e for e in events if e.event_type == "user_message"]
        user_contents = [e.content for e in user_events]
        assert "First message" in user_contents
        assert "Second message" in user_contents

        # There should only be one session (the custom one we created)
        assert len(sessions) == 1, f"Expected 1 session, got {len(sessions)}: {sessions}"

        logger.info("✓ Message processing with provided session_id works correctly")

    @pytest.mark.asyncio
    async def test_session_id_retrieved_via_memory_api(self):
        """Test that session events can be retrieved via memory API after processing."""
        mock_llm = MockModelAPI("memory-api-test")
        memory = LocalMemory()

        agent = Agent(
            name="memory-agent",
            instructions="Test memory API retrieval.",
            model_api=mock_llm,
            memory=memory,
        )

        # Use a specific session ID for easy retrieval
        test_session = "test-session-for-retrieval"
        test_message = "Test message content for verification"

        # Process message
        response_chunks = []
        async for chunk in agent.process_message(test_message, session_id=test_session):
            response_chunks.append(chunk)

        # Retrieve session using memory API
        session = await memory.get_session(test_session)
        assert session is not None, "Session should exist"
        assert session.session_id == test_session

        # Retrieve events using memory API
        events = await memory.get_session_events(test_session)
        assert len(events) >= 2  # At least user_message and agent_response

        # Filter by event type
        user_events = await memory.get_session_events(test_session, event_types=["user_message"])
        assert len(user_events) == 1
        assert user_events[0].content == test_message

        agent_events = await memory.get_session_events(test_session, event_types=["agent_response"])
        assert len(agent_events) == 1

        # Get conversation context
        context = await memory.build_conversation_context(test_session)
        assert test_message in context

        logger.info("✓ Session events retrieved correctly via memory API")


class TestModelAPIClient:
    """Tests for ModelAPI/LiteLLM client."""

    def test_model_api_creation(self):
        """Test ModelAPI can be created with proper configuration."""
        model_api = ModelAPI(model="test-model", api_base="http://localhost:11434")

        assert model_api.model == "test-model"
        assert model_api.api_base == "http://localhost:11434"

        # LiteLLM alias works
        litellm = LiteLLM(model="another-model", api_base="http://localhost:8080")

        assert litellm.model == "another-model"

        logger.info("✓ ModelAPI creation works correctly")


class TestRemoteAgent:
    """Tests for RemoteAgent functionality."""

    @pytest.mark.asyncio
    async def test_remote_agent_creation_and_close(self):
        """Test RemoteAgent can be created and closed properly."""
        remote = RemoteAgent(name="worker", card_url="http://localhost:8001")

        assert remote.name == "worker"
        assert "localhost:8001" in remote.card_url

        # Close should not raise
        await remote.close()

        logger.info("✓ RemoteAgent creation and close work correctly")


class TestAgentServer:
    """Tests for AgentServer creation."""

    def test_agent_server_creation(self):
        """Test AgentServer can be created with an Agent."""
        mock_llm = MockModelAPI("server-agent")

        agent = Agent(name="server-agent", model_api=mock_llm)

        server = AgentServer(agent, port=9999)

        assert server.agent == agent
        assert server.port == 9999
        assert server.app is not None

        logger.info("✓ AgentServer creation works correctly")


class TestMockResponsesReset:
    """Tests for mock responses per-request reset behavior using contextvars."""

    @pytest.mark.asyncio
    async def test_mock_responses_reset_per_request(self, monkeypatch):
        """Test that mock responses reset for each new request.

        Each call to reset_mock_responses() should set up a fresh copy
        in the context for that request to cycle through.
        """
        import json
        from modelapi.client import _mock_responses_ctx

        # Mock responses: a tool_calls response, then text
        mock_responses = json.dumps(
            [
                json.dumps({"tool_calls": [{"id": "call_1", "name": "test", "arguments": {}}]}),
                "Final answer",
            ]
        )
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", mock_responses)

        # Create a real ModelAPI (will pick up env var)
        model_api = ModelAPI(model="test", api_base="http://localhost:8000")

        # Verify mock responses template is configured
        assert model_api.has_mock_responses
        assert model_api._mock_responses_template is not None
        assert len(model_api._mock_responses_template) == 2

        # Initially, context has no mock responses (not reset yet)
        assert _mock_responses_ctx.get() is None

        # First reset - should set all 2 responses in context
        model_api.reset_mock_responses()
        ctx_responses = _mock_responses_ctx.get()
        assert ctx_responses is not None
        assert len(ctx_responses) == 2

        # Consume one response via process_message
        result = await model_api.process_message([{"role": "user", "content": "test"}])
        assert isinstance(result, ModelResponse)
        assert result.has_tool_calls
        ctx_after_consume = _mock_responses_ctx.get()
        assert ctx_after_consume is not None
        assert len(ctx_after_consume) == 1

        # Reset again - should have all 2 responses again
        model_api.reset_mock_responses()
        ctx_after_reset = _mock_responses_ctx.get()
        assert ctx_after_reset is not None
        assert len(ctx_after_reset) == 2

        # Consume first response again (proves reset worked)
        result = await model_api.process_message([{"role": "user", "content": "test"}])
        assert isinstance(result, ModelResponse)
        assert result.has_tool_calls

        await model_api.close()
        logger.info("✓ Mock responses reset correctly per request")

    @pytest.mark.asyncio
    async def test_mock_responses_independent_between_resets(self, monkeypatch):
        """Test that consuming mock responses doesn't affect template."""
        import json
        from modelapi.client import _mock_responses_ctx

        mock_responses = json.dumps(["response1", "response2"])
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", mock_responses)

        model_api = ModelAPI(model="test", api_base="http://localhost:8000")

        # Consume all responses
        model_api.reset_mock_responses()
        result1 = await model_api.process_message([{"role": "user", "content": "test"}])
        assert isinstance(result1, ModelResponse)
        assert result1.content == "response1"
        result2 = await model_api.process_message([{"role": "user", "content": "test"}])
        assert isinstance(result2, ModelResponse)
        assert result2.content == "response2"

        # All consumed from context
        ctx_responses = _mock_responses_ctx.get()
        assert ctx_responses is not None
        assert len(ctx_responses) == 0

        # Template should still be intact
        template = model_api._mock_responses_template
        assert template is not None
        assert len(template) == 2

        # Reset should restore full set in context
        model_api.reset_mock_responses()
        ctx_after_reset = _mock_responses_ctx.get()
        assert ctx_after_reset is not None
        assert len(ctx_after_reset) == 2

        await model_api.close()
        logger.info("✓ Template preserved after consuming responses")
