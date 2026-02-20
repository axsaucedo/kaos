"""
Agentic Loop tests with Pydantic AI integration.

Tests the agentic loop functionality including:
- Tool calling via FunctionModel
- Agent delegation via delegate_to_{name} tool functions
- Memory event verification
- Mock model behavior
- Streaming responses
"""

import json
import os
import pytest
import logging
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock, patch

from pydantic_ai.models.test import TestModel
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse as PydanticModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from agent.client import Agent, RemoteAgent, DELEGATION_TOOL_PREFIX, reset_mock_responses
from agent.memory import LocalMemory, NullMemory

logger = logging.getLogger(__name__)


class TestToolCallExecution:
    """Test tool calling via Pydantic AI FunctionModel."""

    @pytest.mark.asyncio
    async def test_tool_call_detected_and_executed(self):
        """Test that a tool call response triggers tool execution."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="echo",
                            args={"message": "hello"},
                            tool_call_id="call_1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Tool returned: hello")])

        model = FunctionModel(mock_handler)
        agent = Agent(name="tool-agent", model=model, instructions="Test agent")

        # Register a simple tool
        @agent._agent.tool_plain(name="echo", description="Echo a message")
        async def echo(message: str) -> str:
            return f"echo: {message}"

        response = ""
        async for chunk in agent.process_message("Say hello"):
            response += chunk

        assert "Tool returned: hello" in response
        assert call_count == 2  # Tool call + final response

    @pytest.mark.asyncio
    async def test_tool_call_with_arguments(self):
        """Test tool calls pass arguments correctly."""
        received_args = {}
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="calculator",
                            args={"a": 5, "b": 3},
                            tool_call_id="call_1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Result is 8")])

        model = FunctionModel(mock_handler)
        agent = Agent(name="calc-agent", model=model, instructions="Test agent")

        @agent._agent.tool_plain(name="calculator", description="Add two numbers")
        async def calculator(a: int, b: int) -> str:
            received_args["a"] = a
            received_args["b"] = b
            return str(a + b)

        response = ""
        async for chunk in agent.process_message("Add 5 and 3"):
            response += chunk

        assert received_args["a"] == 5
        assert received_args["b"] == 3
        assert "Result is 8" in response

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_sequence(self):
        """Test multiple sequential tool calls in the agentic loop."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="step_one",
                            args={},
                            tool_call_id="call_1",
                        )
                    ]
                )
            elif call_count == 2:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="step_two",
                            args={},
                            tool_call_id="call_2",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Both steps done")])

        model = FunctionModel(mock_handler)
        agent = Agent(name="multi-step-agent", model=model, instructions="Test agent")

        steps_executed = []

        @agent._agent.tool_plain(name="step_one", description="First step")
        async def step_one() -> str:
            steps_executed.append("one")
            return "step one done"

        @agent._agent.tool_plain(name="step_two", description="Second step")
        async def step_two() -> str:
            steps_executed.append("two")
            return "step two done"

        response = ""
        async for chunk in agent.process_message("Do both steps"):
            response += chunk

        assert steps_executed == ["one", "two"]
        assert "Both steps done" in response


class TestDelegation:
    """Test sub-agent delegation as Pydantic AI tools."""

    @pytest.mark.asyncio
    async def test_delegation_tool_registered(self):
        """Test that sub-agents are registered as delegate_to_ tools."""
        model = TestModel(custom_output_text="test")
        sub = RemoteAgent(name="worker-1", card_url="http://localhost:8001")

        agent = Agent(name="coordinator", model=model, sub_agents=[sub])

        assert "worker-1" in agent.sub_agents
        # Verify delegation tool was registered on the Pydantic AI agent
        tool_names = []
        for ts in agent._agent.toolsets:
            if hasattr(ts, "name"):
                tool_names.append(ts.name)
        # Also check via sub_agents dict
        assert len(agent.sub_agents) == 1

        await sub.close()

    @pytest.mark.asyncio
    async def test_delegation_execution_via_mock(self):
        """Test delegation calls RemoteAgent.process_message."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="delegate_to_worker",
                            args={"task": "Process this data"},
                            tool_call_id="call_1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Worker processed the data")])

        model = FunctionModel(mock_handler)
        sub = RemoteAgent(name="worker", card_url="http://localhost:8001")
        sub._active = True

        agent = Agent(name="coordinator", model=model, sub_agents=[sub])

        mock_process = AsyncMock(return_value="Processed data successfully")
        with patch.object(sub, "process_message", mock_process):
            response = ""
            async for chunk in agent.process_message("Delegate to worker"):
                response += chunk

            assert "Worker processed the data" in response
            mock_process.assert_called_once()

        await sub.close()


class TestMemoryWithToolCalls:
    """Test memory event tracking during tool call execution."""

    @pytest.mark.asyncio
    async def test_memory_tracks_tool_call_events(self):
        """Test that tool calls create memory events."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="search",
                            args={"query": "test"},
                            tool_call_id="call_1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Found results")])

        model = FunctionModel(mock_handler)
        memory = LocalMemory()
        agent = Agent(name="memory-agent", model=model, memory=memory, instructions="Test agent")

        @agent._agent.tool_plain(name="search", description="Search for something")
        async def search(query: str) -> str:
            return f"Results for: {query}"

        response = ""
        async for chunk in agent.process_message("Search for test", session_id="mem-session"):
            response += chunk

        events = await memory.get_session_events("mem-session")
        event_types = [e.event_type for e in events]
        assert "user_message" in event_types
        assert "agent_response" in event_types

    @pytest.mark.asyncio
    async def test_memory_context_builds_history(self):
        """Test that memory history is passed to subsequent calls."""
        memory = LocalMemory()
        model = TestModel(custom_output_text="Second response")
        agent = Agent(
            name="history-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        # First message
        async for _ in agent.process_message("First message", session_id="hist-session"):
            pass

        # Second message should have history from first
        async for _ in agent.process_message("Second message", session_id="hist-session"):
            pass

        events = await memory.get_session_events("hist-session")
        user_events = [e for e in events if e.event_type == "user_message"]
        assert len(user_events) == 2
        assert user_events[0].content == "First message"
        assert user_events[1].content == "Second message"


class TestMockModelEnvVar:
    """Test DEBUG_MOCK_RESPONSES environment variable behavior."""

    @pytest.mark.asyncio
    async def test_mock_responses_env_var_text(self, monkeypatch):
        """Test mock responses with plain text."""
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", json.dumps(["Hello from mock!"]))

        agent = Agent(name="mock-agent", instructions="Test agent")

        response = ""
        async for chunk in agent.process_message("Hi"):
            response += chunk

        assert "Hello from mock!" in response

    @pytest.mark.asyncio
    async def test_mock_responses_env_var_tool_calls(self, monkeypatch):
        """Test mock responses with tool_calls JSON."""
        mock_data = [
            json.dumps(
                {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "echo",
                            "arguments": {"message": "test"},
                        }
                    ]
                }
            ),
            "Tool executed successfully.",
        ]
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", json.dumps(mock_data))

        agent = Agent(name="mock-tool-agent", instructions="Test agent")

        @agent._agent.tool_plain(name="echo", description="Echo a message")
        async def echo(message: str) -> str:
            return f"echo: {message}"

        response = ""
        async for chunk in agent.process_message("Use echo tool"):
            response += chunk

        assert "Tool executed successfully" in response

    @pytest.mark.asyncio
    async def test_mock_responses_reset_between_requests(self, monkeypatch):
        """Test that mock responses reset for each new request."""
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", json.dumps(["Response A"]))

        agent = Agent(name="reset-agent", instructions="Test agent")

        # First request
        r1 = ""
        async for chunk in agent.process_message("First"):
            r1 += chunk
        assert "Response A" in r1

        # Second request should also get the same mock response
        r2 = ""
        async for chunk in agent.process_message("Second"):
            r2 += chunk
        assert "Response A" in r2


class TestStreamingResponses:
    """Test streaming message processing."""

    @pytest.mark.asyncio
    async def test_streaming_collects_all_chunks(self):
        """Test that streaming yields chunks that combine to full response."""
        model = TestModel(custom_output_text="Streaming response text")
        agent = Agent(name="stream-agent", model=model, instructions="Test agent")

        chunks = []
        async for chunk in agent.process_message("Stream please", stream=True):
            chunks.append(chunk)

        full_response = "".join(chunks)
        assert len(full_response) > 0

    @pytest.mark.asyncio
    async def test_streaming_stores_complete_response_in_memory(self):
        """Test that streamed responses are stored in memory."""
        model = TestModel(custom_output_text="Complete streamed text")
        memory = LocalMemory()
        agent = Agent(
            name="stream-mem-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        async for _ in agent.process_message("Stream it", session_id="stream-session", stream=True):
            pass

        events = await memory.get_session_events("stream-session")
        agent_events = [e for e in events if e.event_type == "agent_response"]
        assert len(agent_events) >= 1


class TestNoToolsAgent:
    """Test agent behavior without tools (no Phase 1)."""

    @pytest.mark.asyncio
    async def test_agent_without_tools_responds_directly(self):
        """Test agent with no tools goes directly to final response."""
        model = TestModel(custom_output_text="Direct response")
        agent = Agent(name="simple-agent", model=model, instructions="Test agent")

        response = ""
        async for chunk in agent.process_message("Hello"):
            response += chunk

        assert "Direct response" in response

    @pytest.mark.asyncio
    async def test_agent_without_tools_stores_memory_events(self):
        """Test simple agent still stores memory events."""
        model = TestModel(custom_output_text="Simple response")
        memory = LocalMemory()
        agent = Agent(
            name="simple-mem-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        async for _ in agent.process_message("Hello", session_id="simple-session"):
            pass

        events = await memory.get_session_events("simple-session")
        event_types = [e.event_type for e in events]
        assert "user_message" in event_types
        assert "agent_response" in event_types


class TestMessageHistoryBridge:
    """Test conversion between KAOS memory events and Pydantic AI message_history."""

    @pytest.mark.asyncio
    async def test_history_passed_on_second_message(self):
        """Test that conversation history is passed on subsequent calls."""
        messages_received = []

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            messages_received.append(messages)
            return PydanticModelResponse(parts=[TextPart(content="Response")])

        model = FunctionModel(mock_handler)
        memory = LocalMemory()
        agent = Agent(name="history-agent", model=model, memory=memory, instructions="Test agent")

        # First message
        async for _ in agent.process_message("Hello", session_id="h-session"):
            pass

        # Second message should include history
        async for _ in agent.process_message("Follow up", session_id="h-session"):
            pass

        # The second call should have received message_history
        assert len(messages_received) == 2

    @pytest.mark.asyncio
    async def test_null_memory_skips_history(self):
        """Test that NullMemory agent has no history."""
        messages_received = []

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            messages_received.append(messages)
            return PydanticModelResponse(parts=[TextPart(content="Response")])

        model = FunctionModel(mock_handler)
        null_memory = NullMemory()
        agent = Agent(
            name="null-hist-agent",
            model=model,
            memory=null_memory,
            memory_enabled=False,
            instructions="Test agent",
        )

        async for _ in agent.process_message("First"):
            pass
        async for _ in agent.process_message("Second"):
            pass

        # Both calls should have similar message count (no history buildup)
        assert len(messages_received) == 2


class TestErrorHandling:
    """Test error handling in the agentic loop."""

    @pytest.mark.asyncio
    async def test_error_yields_error_message(self):
        """Test that errors in processing yield error messages."""

        def broken_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            raise RuntimeError("Model crashed")

        model = FunctionModel(broken_handler)
        agent = Agent(name="error-agent", model=model, instructions="Test agent")

        response = ""
        async for chunk in agent.process_message("Break please"):
            response += chunk

        assert "error" in response.lower()

    @pytest.mark.asyncio
    async def test_error_stores_error_event_in_memory(self):
        """Test that errors create error events in memory."""

        def broken_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            raise RuntimeError("Model crashed")

        model = FunctionModel(broken_handler)
        memory = LocalMemory()
        agent = Agent(
            name="error-mem-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        async for _ in agent.process_message("Break", session_id="err-session"):
            pass

        events = await memory.get_session_events("err-session")
        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) >= 1


class TestAgentConfiguration:
    """Test agent configuration options."""

    def test_default_max_steps(self):
        """Test default max_steps value."""
        model = TestModel(custom_output_text="test")
        agent = Agent(name="default-agent", model=model)
        assert agent.max_steps == 5

    def test_custom_max_steps(self):
        """Test custom max_steps value."""
        model = TestModel(custom_output_text="test")
        agent = Agent(name="custom-agent", model=model, max_steps=10)
        assert agent.max_steps == 10

    def test_default_memory_context_limit(self):
        """Test default memory context limit."""
        model = TestModel(custom_output_text="test")
        agent = Agent(name="mem-limit-agent", model=model)
        assert agent.memory_context_limit == 6

    def test_custom_memory_context_limit(self):
        """Test custom memory context limit."""
        model = TestModel(custom_output_text="test")
        agent = Agent(name="mem-limit-agent", model=model, memory_context_limit=20)
        assert agent.memory_context_limit == 20

    def test_model_from_url_and_name(self):
        """Test creating agent from model_api_url and model_name."""
        agent = Agent(
            name="url-agent",
            model_api_url="http://localhost:11434/v1",
            model_name="test-model",
        )
        assert agent.name == "url-agent"

    def test_agent_requires_model_source(self):
        """Test agent creation without model source raises error."""
        with pytest.raises(ValueError, match="Agent requires"):
            Agent(name="no-model-agent")

    def test_memory_enabled_flag(self):
        """Test memory_enabled flag."""
        model = TestModel(custom_output_text="test")
        agent = Agent(name="no-mem-agent", model=model, memory_enabled=False)
        assert not agent.memory_enabled


class TestUserPromptExtraction:
    """Test user prompt extraction from various message formats."""

    @pytest.mark.asyncio
    async def test_string_message(self):
        """Test extracting prompt from string."""
        model = TestModel(custom_output_text="Got it")
        agent = Agent(name="extract-agent", model=model, instructions="Test agent")

        response = ""
        async for chunk in agent.process_message("Hello world"):
            response += chunk

        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_message_array(self):
        """Test extracting prompt from OpenAI-style message array."""
        model = TestModel(custom_output_text="Got it")
        agent = Agent(name="extract-agent", model=model, instructions="Test agent")

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello from array"},
        ]

        response = ""
        async for chunk in agent.process_message(messages):
            response += chunk

        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_task_delegation_role(self):
        """Test extracting prompt from task-delegation role."""
        model = TestModel(custom_output_text="Task received")
        agent = Agent(name="task-agent", model=model, instructions="Test agent")

        messages = [
            {"role": "task-delegation", "content": "Process this task"},
        ]

        response = ""
        async for chunk in agent.process_message(messages):
            response += chunk

        assert len(response) > 0
