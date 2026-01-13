"""
Consolidated Agent tests.

Tests Agent, RemoteAgent, AgentCard, LocalMemory, and ModelAPI functionality.
Focuses on meaningful integration between components.
"""

import pytest
import logging
from unittest.mock import Mock, AsyncMock
from typing import List, Dict, Optional

from agent.client import Agent, RemoteAgent, AgentCard
from agent.memory import LocalMemory
from agent.server import AgentServer
from modelapi.client import ModelAPI, LiteLLM

logger = logging.getLogger(__name__)


class MockModelAPI(ModelAPI):
    """Mock ModelAPI for testing."""

    def __init__(self, name: str = "mock"):
        self.name = name
        self.call_count = 0
        self.model = "mock"
        self.api_base = "mock://localhost"
        self._mock_responses: Optional[List[str]] = None  # Not used in this mock

    async def process_message(self, messages: List[Dict], stream: bool = False):
        """Return a mock response based on the name.

        Returns str if stream=False, AsyncIterator[str] if stream=True.
        """
        self.call_count += 1
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        content = f"[{self.name}] Response to: {user_msg}"
        if stream:
            return self._yield_content(content)
        return content

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

        # Test AgentCard generation
        card = agent.get_agent_card("http://localhost:8000")

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

        # Card should indicate delegation capability
        card = agent.get_agent_card("http://localhost:8000")
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
