"""
Tests for KAOS Agent with Pydantic AI integration.

Tests Agent creation, memory, message processing, and AgentCard.
"""

import os
import pytest
import logging
from typing import List, Dict, Optional

from pydantic_ai.models.test import TestModel
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.messages import ModelResponse as PydanticModelResponse, TextPart, ToolCallPart
from pydantic_ai import Agent as PydanticAgent

from tests.helpers import make_test_server
from pais.serverutils import AgentCard, AgentCardSkill, AgentCardCapabilities, RemoteAgent
from pais.memory import LocalMemory, NullMemory, RedisMemory

logger = logging.getLogger(__name__)


class TestAgentCreationAndCard:
    """Tests for Agent creation and AgentCard generation."""

    @pytest.mark.asyncio
    async def test_agent_creation_with_test_model(self):
        """Test Agent can be created with Pydantic AI TestModel."""
        model = TestModel(custom_output_text="Hello from test")
        memory = LocalMemory()

        server = make_test_server(
            name="test-agent",
            description="Test Agent Description",
            instructions="You are a test assistant.",
            model=model,
            memory=memory,
        )

        assert server.settings.agent_name == "test-agent"
        assert server.settings.agent_description == "Test Agent Description"
        assert server.memory == memory

    @pytest.mark.asyncio
    async def test_agent_card_generation(self):
        """Test AgentCard generation."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(
            name="test-agent",
            description="Test Agent Description",
            instructions="You are a test assistant.",
            model=model,
        )

        card = await server._get_agent_card("http://localhost:8000")
        assert card.name == "test-agent"
        assert card.description == "Test Agent Description"
        assert card.url == "http://localhost:8000"
        assert card.version is not None
        assert card.protocol_version == "0.3.0"
        assert isinstance(card.capabilities, AgentCardCapabilities)
        assert card.capabilities.streaming is True

        card_dict = card.to_dict()
        assert "name" in card_dict
        assert "description" in card_dict
        assert "url" in card_dict
        assert "skills" in card_dict
        assert "protocolVersion" in card_dict
        assert "capabilities" in card_dict
        assert isinstance(card_dict["capabilities"], dict)
        assert card_dict["capabilities"]["streaming"] is True

    @pytest.mark.asyncio
    async def test_agent_creation_requires_model_source(self):
        """Test _resolve_model raises ValueError when no model source is provided."""
        from pais.serverutils import _resolve_model

        with pytest.raises(ValueError, match="Agent requires either"):
            _resolve_model("test-agent")


class TestAgentMessageProcessing:
    """Tests for Agent message processing with Pydantic AI."""

    @pytest.mark.asyncio
    async def test_simple_message_processing(self):
        """Test simple non-streaming message processing."""
        model = TestModel(custom_output_text="Hello, world!")
        server = make_test_server(
            name="test-agent",
            model=model,
            instructions="You are a test assistant.",
        )

        response = ""
        async for chunk in server._process_message("Hi there", session_id="test"):
            response += chunk

        assert "Hello, world!" in response

    @pytest.mark.asyncio
    async def test_message_processing_with_session(self):
        """Test message processing with session ID."""
        model = TestModel(custom_output_text="Session response")
        memory = LocalMemory()
        server = make_test_server(
            name="test-agent",
            model=model,
            memory=memory,
            instructions="You are a test assistant.",
        )

        response = ""
        async for chunk in server._process_message("Hello", session_id="test-session"):
            response += chunk

        assert "Session response" in response

        # Verify memory has events
        sessions = await memory.list_sessions()
        assert len(sessions) >= 1

    @pytest.mark.asyncio
    async def test_message_processing_with_message_array(self):
        """Test processing message as array format."""
        model = TestModel(custom_output_text="Array response")
        server = make_test_server(
            name="test-agent",
            model=model,
            instructions="You are a test assistant.",
        )

        messages = [
            {"role": "user", "content": "Hello from array"},
        ]

        response = ""
        async for chunk in server._process_message(messages, session_id="test"):
            response += chunk

        assert "Array response" in response

    @pytest.mark.asyncio
    async def test_streaming_message_processing(self):
        """Test streaming message processing."""
        model = TestModel(custom_output_text="Streaming response")
        server = make_test_server(
            name="test-agent",
            model=model,
            instructions="You are a test assistant.",
        )

        chunks = []
        async for chunk in server._process_message("Hi", session_id="test", stream=True):
            chunks.append(chunk)

        full_response = "".join(chunks)
        assert "Streaming" in full_response


class TestAgentMemory:
    """Tests for Agent memory integration."""

    @pytest.mark.asyncio
    async def test_null_memory(self):
        """Test agent with NullMemory (disabled)."""
        model = TestModel(custom_output_text="No memory")
        server = make_test_server(
            name="test-agent",
            model=model,
            memory=NullMemory(),
            instructions="You are a test assistant.",
        )

        response = ""
        async for chunk in server._process_message("Hello", session_id="test"):
            response += chunk

        assert "No memory" in response

    @pytest.mark.asyncio
    async def test_local_memory_events(self):
        """Test that memory events are stored correctly."""
        model = TestModel(custom_output_text="Memory test")
        memory = LocalMemory()
        server = make_test_server(
            name="test-agent",
            model=model,
            memory=memory,
            instructions="You are a test assistant.",
        )

        response = ""
        async for chunk in server._process_message("Hello", session_id="mem-test"):
            response += chunk

        # Check events were stored
        sessions = await memory.list_sessions()
        assert len(sessions) >= 1

        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]
        assert "user_message" in event_types
        assert "agent_response" in event_types


class TestMockModel:
    """Tests for DEBUG_MOCK_RESPONSES support."""

    @pytest.mark.asyncio
    async def test_mock_responses_plain_text(self):
        """Test mock model with plain text responses."""
        os.environ["DEBUG_MOCK_RESPONSES"] = '["Hello from mock"]'
        try:
            server = make_test_server(
                name="mock-agent",
                instructions="You are a test assistant.",
            )

            response = ""
            async for chunk in server._process_message("Test", session_id="test"):
                response += chunk

            assert "Hello from mock" in response
        finally:
            del os.environ["DEBUG_MOCK_RESPONSES"]

    @pytest.mark.asyncio
    async def test_mock_responses_with_tool_calls(self):
        """Test mock model with tool call responses."""
        mock_responses = [
            '{"tool_calls": [{"name": "echo", "arguments": {"message": "hello"}, "id": "call_1"}]}',
            "No more actions.",
            "The echo returned hello.",
        ]
        os.environ["DEBUG_MOCK_RESPONSES"] = str(mock_responses).replace("'", '"')
        try:
            call_count = 0

            def mock_fn(messages, info):
                nonlocal call_count
                call_count += 1
                if call_count == 1 and info.function_tools:
                    tool = info.function_tools[0]
                    return PydanticModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name=tool.name,
                                args={"message": "hello"},
                                tool_call_id="call_1",
                            )
                        ]
                    )
                return PydanticModelResponse(parts=[TextPart(content="Done with tools.")])

            model = FunctionModel(mock_fn)
            server = make_test_server(
                name="tool-agent",
                model=model,
                instructions="You are a test assistant.",
            )

            @server._agent.tool_plain
            def echo(message: str) -> str:
                """Echo a message."""
                return f"Echo: {message}"

            response = ""
            async for chunk in server._process_message("Test tools", session_id="test"):
                response += chunk

            assert "Done with tools" in response
        finally:
            del os.environ["DEBUG_MOCK_RESPONSES"]


class TestAgentCard:
    """Tests for AgentCard dataclass."""

    def test_agent_card_to_dict(self):
        """Test AgentCard serialization."""
        card = AgentCard(
            name="test",
            description="Test agent",
            url="http://localhost:8000",
            version="0.1.0",
            skills=[AgentCardSkill(id="echo", name="echo", description="Echo tool")],
            capabilities=AgentCardCapabilities(streaming=True),
        )
        d = card.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "Test agent"
        assert d["url"] == "http://localhost:8000"
        assert d["version"] == "0.1.0"
        assert d["protocolVersion"] == "0.3.0"
        assert len(d["skills"]) == 1
        assert d["skills"][0]["id"] == "echo"
        assert d["skills"][0]["name"] == "echo"
        assert d["capabilities"]["streaming"] is True
        assert d["capabilities"]["pushNotifications"] is False
        assert "defaultInputModes" in d
        assert "defaultOutputModes" in d

    @pytest.mark.asyncio
    async def test_agent_with_sub_agents(self):
        """Test Agent with sub-agents has delegation capability and dict access."""
        model = TestModel(custom_output_text="coordinator response")

        sub_agent1 = RemoteAgent(name="worker-1", card_url="http://localhost:8001")
        sub_agent2 = RemoteAgent(name="worker-2", card_url="http://localhost:8002")

        server = make_test_server(
            name="coordinator",
            model=model,
            sub_agents=[sub_agent1, sub_agent2],
        )

        assert isinstance(server._sub_agents, dict)
        assert len(server._sub_agents) == 2
        assert "worker-1" in server._sub_agents
        assert "worker-2" in server._sub_agents
        assert server._sub_agents["worker-1"] is sub_agent1
        assert server._sub_agents["worker-2"] is sub_agent2

        card = await server._get_agent_card("http://localhost:8000")
        delegation_skills = [s for s in card.skills if "delegate_to_" in s.name]
        assert len(delegation_skills) == 2

        await sub_agent1.close()
        await sub_agent2.close()


class TestMemorySystem:
    """Tests for LocalMemory functionality."""

    @pytest.mark.asyncio
    async def test_memory_system_complete_workflow(self):
        """Test complete memory workflow: sessions, events, context."""
        memory = LocalMemory()

        session_id = await memory.create_session("test_app", "test_user")
        assert session_id is not None

        sessions = await memory.list_sessions()
        assert session_id in sessions

        await memory.add_event(session_id, "user_message", "Hello agent!")
        await memory.add_event(session_id, "agent_response", "Hello user!")
        await memory.add_event(session_id, "tool_call", {"tool": "calculator", "args": {"a": 1}})

        events = await memory.get_session_events(session_id)
        assert len(events) == 3
        assert events[0].event_type == "user_message"
        assert events[0].content == "Hello agent!"
        assert events[1].event_type == "agent_response"
        assert events[2].event_type == "tool_call"

        context = await memory.build_conversation_context(session_id)
        assert "Hello agent!" in context
        assert "Hello user!" in context

    @pytest.mark.asyncio
    async def test_deque_based_event_storage_auto_eviction(self):
        """Test that deque-based storage automatically evicts old events."""
        memory = LocalMemory(max_sessions=10, max_events_per_session=5)

        session_id = await memory.create_session("test_app", "test_user")

        for i in range(7):
            await memory.add_event(session_id, "user_message", f"Message {i}")

        events = await memory.get_session_events(session_id)
        assert len(events) == 5

        contents = [e.content for e in events]
        assert "Message 2" in contents
        assert "Message 6" in contents
        assert "Message 0" not in contents
        assert "Message 1" not in contents


class TestNullMemory:
    """Tests for NullMemory (disabled memory) functionality."""

    @pytest.mark.asyncio
    async def test_null_memory_all_operations_succeed(self):
        """Test NullMemory operations all succeed silently."""
        memory = NullMemory()

        session_id = await memory.create_session("app", "user")
        assert session_id == "null-session"

        custom_session = await memory.create_session("app", "user", "custom-id")
        assert custom_session == "custom-id"

        session = await memory.get_or_create_session("my-session")
        assert session == "my-session"

        assert await memory.get_session("any-id") is None

        events = await memory.get_session_events("any-session")
        assert events == []

        context = await memory.build_conversation_context("any-session")
        assert context == ""

        sessions = await memory.list_sessions()
        assert sessions == []

        deleted = await memory.delete_session("any-session")
        assert deleted is True

        stats = await memory.get_memory_stats()
        assert stats["total_sessions"] == 0
        assert stats["total_events"] == 0

        cleaned = await memory.cleanup_old_sessions()
        assert cleaned == 0

    @pytest.mark.asyncio
    async def test_agent_with_null_memory_processes_messages(self):
        """Test Agent works correctly with NullMemory."""
        model = TestModel(custom_output_text="No memory response")
        null_memory = NullMemory()

        server = make_test_server(
            name="null-memory-agent",
            instructions="Test agent with disabled memory.",
            model=model,
            memory=null_memory,
        )

        response_chunks = []
        async for chunk in server._process_message("Hello!", session_id="test"):
            response_chunks.append(chunk)

        response = "".join(response_chunks)
        assert len(response) > 0

        sessions = await null_memory.list_sessions()
        assert sessions == []


class TestRedisMemory:
    """Tests for RedisMemory verifying actual Redis commands issued."""

    def _make_redis_memory(self, mock_redis):
        from unittest.mock import patch
        from pais.memory import RedisMemory

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            return RedisMemory(redis_url="redis://localhost:6379", max_events_per_session=10)

    @pytest.mark.asyncio
    async def test_create_session_issues_hset_and_zadd(self):
        from unittest.mock import AsyncMock, MagicMock
        from pais.memory import RedisMemory

        mock_redis = AsyncMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.zcard = AsyncMock(return_value=0)

        memory = self._make_redis_memory(mock_redis)
        sid = await memory.create_session("app", "user1", "s1")
        assert sid == "s1"
        mock_pipe.hset.assert_called_once()
        mock_pipe.zadd.assert_called_once()
        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        from unittest.mock import AsyncMock, MagicMock

        mock_redis = AsyncMock()
        memory = self._make_redis_memory(mock_redis)
        await memory.close()
        mock_redis.aclose.assert_awaited_once()


class TestMessageProcessing:
    """Tests for agent message processing with memory."""

    @pytest.mark.asyncio
    async def test_message_processing_creates_memory_events(self):
        """Test message processing creates expected memory events."""
        model = TestModel(custom_output_text="Test response")
        memory = LocalMemory()

        server = make_test_server(
            name="test-agent",
            model=model,
            memory=memory,
            instructions="You are a test assistant.",
        )

        response = ""
        async for chunk in server._process_message("Hello agent!", session_id="test"):
            response += chunk

        assert "Test response" in response

        sessions = await memory.list_sessions()
        assert len(sessions) >= 1

        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]
        assert "user_message" in event_types
        assert "agent_response" in event_types

    @pytest.mark.asyncio
    async def test_message_processing_with_provided_session_id(self):
        """Test that provided session ID is used."""
        model = TestModel(custom_output_text="Session response")
        memory = LocalMemory()

        server = make_test_server(
            name="test-agent",
            model=model,
            memory=memory,
            instructions="You are a test assistant.",
        )

        response = ""
        async for chunk in server._process_message("Hello", session_id="my-session"):
            response += chunk

        sessions = await memory.list_sessions()
        assert "my-session" in sessions


class TestRemoteAgent:
    """Tests for RemoteAgent."""

    @pytest.mark.asyncio
    async def test_remote_agent_creation_and_close(self):
        """Test RemoteAgent can be created and closed."""
        remote = RemoteAgent(name="test-remote", card_url="http://localhost:9999")
        assert remote.name == "test-remote"
        assert remote.card_url == "http://localhost:9999"
        assert not remote._active
        await remote.close()


class TestAgentServer:
    """Tests for AgentServer creation."""

    def test_agent_server_creation(self):
        """Test AgentServer can be created with a PydanticAgent."""
        from pais.server import AgentServer as ServerClass
        from pais.serverutils import AgentDeps, AgentServerSettings

        model = TestModel(custom_output_text="server test")
        pydantic_agent = PydanticAgent(
            model=model,
            instructions="Test server agent.",
            name="server-test-agent",
            defer_model_check=True,
            deps_type=AgentDeps,
        )
        settings = AgentServerSettings(agent_name="server-test-agent")
        server = ServerClass(
            pydantic_agent=pydantic_agent,
            settings=settings,
        )
        assert server.settings.agent_name == "server-test-agent"
        assert server.app is not None
