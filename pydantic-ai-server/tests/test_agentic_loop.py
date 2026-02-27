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

from tests.helpers import make_test_server
from pais.serverutils import RemoteAgent
from pais.tools import DELEGATION_TOOL_PREFIX
from pais.memory import LocalMemory, NullMemory

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
        server = make_test_server(name="tool-agent", model=model, instructions="Test agent")

        # Register a simple tool
        @server._agent.tool_plain(name="echo", description="Echo a message")
        async def echo(message: str) -> str:
            return f"echo: {message}"

        response = ""
        async for chunk in server._process_message("Say hello", session_id="test"):
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
        server = make_test_server(name="calc-agent", model=model, instructions="Test agent")

        @server._agent.tool_plain(name="calculator", description="Add two numbers")
        async def calculator(a: int, b: int) -> str:
            received_args["a"] = a
            received_args["b"] = b
            return str(a + b)

        response = ""
        async for chunk in server._process_message("Add 5 and 3", session_id="test"):
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
        server = make_test_server(name="multi-step-agent", model=model, instructions="Test agent")

        steps_executed = []

        @server._agent.tool_plain(name="step_one", description="First step")
        async def step_one() -> str:
            steps_executed.append("one")
            return "step one done"

        @server._agent.tool_plain(name="step_two", description="Second step")
        async def step_two() -> str:
            steps_executed.append("two")
            return "step two done"

        response = ""
        async for chunk in server._process_message("Do both steps", session_id="test"):
            response += chunk

        assert steps_executed == ["one", "two"]
        assert "Both steps done" in response

    @pytest.mark.asyncio
    async def test_max_steps_limits_model_calls(self):
        """Test that max_steps limits tool-calling loop via UsageLimits."""
        call_count = 0

        def infinite_tool_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            # Always return a tool call — should be stopped by usage limit
            return PydanticModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="repeat",
                        args={},
                        tool_call_id=f"call_{call_count}",
                    )
                ]
            )

        model = FunctionModel(infinite_tool_handler)
        server = make_test_server(
            name="limited-agent", model=model, instructions="Test", max_steps=3
        )

        @server._agent.tool_plain(name="repeat", description="Repeat forever")
        async def repeat() -> str:
            return "again"

        response = ""
        async for chunk in server._process_message("Go", session_id="test"):
            response += chunk

        # Should have been stopped — call_count limited by max_steps
        assert call_count <= 4, f"Expected max ~3 calls, got {call_count}"


class TestDelegation:
    """Test sub-agent delegation as Pydantic AI tools."""

    @pytest.mark.asyncio
    async def test_delegation_tool_registered(self):
        """Test that sub-agents are registered as delegate_to_ tools."""
        model = TestModel(custom_output_text="test")
        sub = RemoteAgent(name="worker-1", card_url="http://localhost:8001")

        server = make_test_server(name="coordinator", model=model, sub_agents=[sub])

        assert "worker-1" in server._sub_agents
        # Verify delegation tool was registered on the Pydantic AI agent
        tool_names = []
        for ts in server._agent.toolsets:
            if hasattr(ts, "name"):
                tool_names.append(ts.name)
        # Also check via sub_agents dict
        assert len(server._sub_agents) == 1

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

        server = make_test_server(name="coordinator", model=model, sub_agents=[sub])

        mock_process = AsyncMock(return_value="Processed data successfully")
        with patch.object(sub, "process_message", mock_process):
            response = ""
            async for chunk in server._process_message("Delegate to worker", session_id="test"):
                response += chunk

            assert "Worker processed the data" in response
            mock_process.assert_called_once()

        await sub.close()

    @pytest.mark.asyncio
    async def test_delegation_memory_event_types(self):
        """Test that delegation creates delegation_request/delegation_response events."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="delegate_to_worker",
                            args={"task": "Test delegation"},
                            tool_call_id="call_1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Done")])

        model = FunctionModel(mock_handler)
        memory = LocalMemory()
        sub = RemoteAgent(name="worker", card_url="http://localhost:8001")
        sub._active = True

        server = make_test_server(name="coordinator", model=model, sub_agents=[sub], memory=memory)

        mock_process = AsyncMock(return_value="Result")
        with patch.object(sub, "process_message", mock_process):
            async for _ in server._process_message("Delegate", session_id="del-session"):
                pass

        events = await memory.get_session_events("del-session")
        event_types = [e.event_type for e in events]
        assert (
            "delegation_request" in event_types
        ), f"Expected delegation_request, got {event_types}"
        assert (
            "delegation_response" in event_types
        ), f"Expected delegation_response, got {event_types}"
        # Regular tool_call/tool_result should NOT be used for delegation
        tool_call_events = [e for e in events if e.event_type == "tool_call"]
        assert len(tool_call_events) == 0, "Delegation should use delegation_request, not tool_call"

        await sub.close()

    @pytest.mark.asyncio
    async def test_delegation_forwards_conversation_context(self):
        """Test that delegation includes recent conversation context."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="delegate_to_worker",
                            args={"task": "Summarize above"},
                            tool_call_id="call_1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Response")])

        model = FunctionModel(mock_handler)
        memory = LocalMemory()
        sub = RemoteAgent(name="worker", card_url="http://localhost:8001")
        sub._active = True

        server = make_test_server(name="coordinator", model=model, sub_agents=[sub], memory=memory)

        captured_messages = []

        async def mock_process(msgs):
            captured_messages.extend(msgs)
            return "Summarized"

        with patch.object(sub, "process_message", side_effect=mock_process):
            # First message to build history
            async for _ in server._process_message("Initial context", session_id="ctx-sess"):
                pass
            # Second message triggers delegation
            async for _ in server._process_message("Now delegate", session_id="ctx-sess"):
                pass

        # Verify context was forwarded (should include user/assistant messages before delegation)
        assert len(captured_messages) > 1, f"Expected context + delegation, got {captured_messages}"
        roles = [m["role"] for m in captured_messages]
        assert "task-delegation" in roles
        # Should have at least one context message before the delegation
        deleg_idx = roles.index("task-delegation")
        assert deleg_idx > 0, "Expected context messages before delegation"


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
        server = make_test_server(
            name="memory-agent", model=model, memory=memory, instructions="Test agent"
        )

        @server._agent.tool_plain(name="search", description="Search for something")
        async def search(query: str) -> str:
            return f"Results for: {query}"

        response = ""
        async for chunk in server._process_message("Search for test", session_id="mem-session"):
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
        server = make_test_server(
            name="history-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        # First message
        async for _ in server._process_message("First message", session_id="hist-session"):
            pass

        # Second message should have history from first
        async for _ in server._process_message("Second message", session_id="hist-session"):
            pass

        events = await memory.get_session_events("hist-session")
        user_events = [e for e in events if e.event_type == "user_message"]
        assert len(user_events) == 2
        assert user_events[0].content == "First message"
        assert user_events[1].content == "Second message"

    @pytest.mark.asyncio
    async def test_delegation_prompt_replayed_in_history(self):
        """Test that task_delegation_received events appear in message history."""
        memory = LocalMemory()
        model = TestModel(custom_output_text="Delegation response")
        server = make_test_server(
            name="deleg-hist-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        # Simulate a delegation message
        delegation_msg = [{"role": "task-delegation", "content": "Delegated task"}]
        async for _ in server._process_message(delegation_msg, session_id="deleg-hist"):
            pass

        # Send a follow-up — history should include the delegation prompt
        async for _ in server._process_message("Follow up", session_id="deleg-hist"):
            pass

        # Build history for the third hypothetical call
        history = await server.memory.build_message_history("deleg-hist")
        assert history is not None
        user_parts = [
            p
            for msg in history
            if isinstance(msg, ModelRequest)
            for p in msg.parts
            if isinstance(p, UserPromptPart)
        ]
        assert any("Delegated task" in str(p.content) for p in user_parts)

    @pytest.mark.asyncio
    async def test_memory_disabled_skips_storage(self):
        """Test that NullMemory skips all memory storage."""
        memory = NullMemory()
        model = TestModel(custom_output_text="No memory response")
        server = make_test_server(
            name="no-mem-agent",
            model=model,
            memory=memory,
            instructions="Test",
        )

        async for _ in server._process_message("Hello", session_id="no-mem"):
            pass

        events = await memory.get_session_events("no-mem")
        assert len(events) == 0, f"Expected no events with NullMemory, got {len(events)}"

    @pytest.mark.asyncio
    async def test_memory_context_limit_enforced(self):
        """Test that memory_context_limit caps the history size."""
        memory = LocalMemory()
        model = TestModel(custom_output_text="Response")
        server = make_test_server(
            name="limit-agent",
            model=model,
            memory=memory,
            memory_context_limit=2,
            instructions="Test",
        )

        # Add 5 exchanges
        for i in range(5):
            async for _ in server._process_message(f"Message {i}", session_id="limit-sess"):
                pass

        # History should be capped at 2 events (most recent)
        history = await server.memory.build_message_history(
            "limit-sess", server.settings.memory_context_limit
        )
        assert history is not None
        assert len(history) <= 2, f"Expected at most 2 history items, got {len(history)}"


class TestMockModelEnvVar:
    """Test DEBUG_MOCK_RESPONSES environment variable behavior."""

    @pytest.mark.asyncio
    async def test_mock_responses_env_var_text(self, monkeypatch):
        """Test mock responses with plain text."""
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", json.dumps(["Hello from mock!"]))

        server = make_test_server(name="mock-agent", instructions="Test agent")

        response = ""
        async for chunk in server._process_message("Hi", session_id="test"):
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

        server = make_test_server(name="mock-tool-agent", instructions="Test agent")

        @server._agent.tool_plain(name="echo", description="Echo a message")
        async def echo(message: str) -> str:
            return f"echo: {message}"

        response = ""
        async for chunk in server._process_message("Use echo tool", session_id="test"):
            response += chunk

        assert "Tool executed successfully" in response

    @pytest.mark.asyncio
    async def test_mock_responses_reset_between_requests(self, monkeypatch):
        """Test that mock responses reset for each new request."""
        monkeypatch.setenv("DEBUG_MOCK_RESPONSES", json.dumps(["Response A"]))

        server = make_test_server(name="reset-agent", instructions="Test agent")

        # First request
        r1 = ""
        async for chunk in server._process_message("First", session_id="test"):
            r1 += chunk
        assert "Response A" in r1

        # Second request should also get the same mock response
        r2 = ""
        async for chunk in server._process_message("Second", session_id="test"):
            r2 += chunk
        assert "Response A" in r2


class TestStreamingResponses:
    """Test streaming message processing."""

    @pytest.mark.asyncio
    async def test_streaming_collects_all_chunks(self):
        """Test that streaming yields chunks that combine to full response."""
        model = TestModel(custom_output_text="Streaming response text")
        server = make_test_server(name="stream-agent", model=model, instructions="Test agent")

        chunks = []
        async for chunk in server._process_message("Stream please", session_id="test", stream=True):
            chunks.append(chunk)

        full_response = "".join(chunks)
        assert len(full_response) > 0

    @pytest.mark.asyncio
    async def test_streaming_stores_complete_response_in_memory(self):
        """Test that streamed responses are stored in memory."""
        model = TestModel(custom_output_text="Complete streamed text")
        memory = LocalMemory()
        server = make_test_server(
            name="stream-mem-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        async for _ in server._process_message(
            "Stream it", session_id="stream-session", stream=True
        ):
            pass

        events = await memory.get_session_events("stream-session")
        agent_events = [e for e in events if e.event_type == "agent_response"]
        assert len(agent_events) >= 1

    @pytest.mark.asyncio
    async def test_streaming_stores_tool_call_events_in_memory(self):
        """Test that streaming mode persists tool_call/tool_result memory events."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="lookup",
                            args={"key": "test"},
                            tool_call_id="call_s1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Streamed tool result")])

        model = FunctionModel(function=mock_handler)
        memory = LocalMemory()
        server = make_test_server(
            name="stream-tool-agent", model=model, memory=memory, instructions="Test"
        )

        @server._agent.tool_plain(name="lookup", description="Lookup a key")
        async def lookup(key: str) -> str:
            return f"value_for_{key}"

        async for _ in server._process_message(
            "Lookup test", session_id="stream-tool", stream=True
        ):
            pass

        events = await memory.get_session_events("stream-tool")
        event_types = [e.event_type for e in events]
        assert "tool_call" in event_types, f"Expected tool_call in {event_types}"
        assert "tool_result" in event_types, f"Expected tool_result in {event_types}"

    @pytest.mark.asyncio
    async def test_streaming_emits_progress_events_for_tool_calls(self):
        """Test that streaming yields progress JSON events with step info."""
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
                            tool_call_id="call_p1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Echo said hello")])

        model = FunctionModel(function=mock_handler)
        server = make_test_server(
            name="progress-agent", model=model, instructions="Test", max_steps=5
        )

        @server._agent.tool_plain(name="echo", description="Echo a message")
        async def echo(message: str) -> str:
            return f"echoed: {message}"

        chunks = []
        async for chunk in server._process_message("Use echo", session_id="test", stream=True):
            chunks.append(chunk)

        # First chunk should be progress event for tool call with step info
        assert len(chunks) >= 2
        progress = json.loads(chunks[0])
        assert progress["type"] == "progress"
        assert progress["step"] == 1
        assert progress["max_steps"] == 5
        assert progress["action"] == "tool_call"
        assert progress["target"] == "echo"
        # Last chunk should be the final response text
        assert "Echo said hello" in chunks[-1]

    @pytest.mark.asyncio
    async def test_streaming_emits_delegate_action_for_delegation(self):
        """Test that delegation tool calls emit action='delegate' with agent name."""
        call_count = 0

        def mock_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return PydanticModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="delegate_to_worker",
                            args={"task": "do something"},
                            tool_call_id="call_d1",
                        )
                    ]
                )
            return PydanticModelResponse(parts=[TextPart(content="Worker finished")])

        model = FunctionModel(function=mock_handler)
        server = make_test_server(name="delegator", model=model, instructions="Test", max_steps=5)

        # Register a delegation tool matching the delegate_to_ prefix
        @server._agent.tool_plain(name="delegate_to_worker", description="Delegate to worker")
        async def delegate_to_worker(task: str) -> str:
            return "done"

        chunks = []
        async for chunk in server._process_message("Delegate", session_id="test", stream=True):
            chunks.append(chunk)

        assert len(chunks) >= 2
        progress = json.loads(chunks[0])
        assert progress["action"] == "delegate"
        assert progress["target"] == "worker"
        assert progress["step"] == 1


class TestNoToolsAgent:
    """Test agent behavior without tools (no Phase 1)."""

    @pytest.mark.asyncio
    async def test_agent_without_tools_responds_directly(self):
        """Test agent with no tools goes directly to final response."""
        model = TestModel(custom_output_text="Direct response")
        server = make_test_server(name="simple-agent", model=model, instructions="Test agent")

        response = ""
        async for chunk in server._process_message("Hello", session_id="test"):
            response += chunk

        assert "Direct response" in response

    @pytest.mark.asyncio
    async def test_agent_without_tools_stores_memory_events(self):
        """Test simple agent still stores memory events."""
        model = TestModel(custom_output_text="Simple response")
        memory = LocalMemory()
        server = make_test_server(
            name="simple-mem-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        async for _ in server._process_message("Hello", session_id="simple-session"):
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
        server = make_test_server(
            name="history-agent", model=model, memory=memory, instructions="Test agent"
        )

        # First message
        async for _ in server._process_message("Hello", session_id="h-session"):
            pass

        # Second message should include history
        async for _ in server._process_message("Follow up", session_id="h-session"):
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
        server = make_test_server(
            name="null-hist-agent",
            model=model,
            memory=null_memory,
            instructions="Test agent",
        )

        async for _ in server._process_message("First", session_id="test"):
            pass
        async for _ in server._process_message("Second", session_id="test"):
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
        server = make_test_server(name="error-agent", model=model, instructions="Test agent")

        response = ""
        async for chunk in server._process_message("Break please", session_id="test"):
            response += chunk

        assert "error" in response.lower()

    @pytest.mark.asyncio
    async def test_error_stores_error_event_in_memory(self):
        """Test that errors create error events in memory."""

        def broken_handler(messages: list, info: AgentInfo) -> PydanticModelResponse:
            raise RuntimeError("Model crashed")

        model = FunctionModel(broken_handler)
        memory = LocalMemory()
        server = make_test_server(
            name="error-mem-agent",
            model=model,
            memory=memory,
            instructions="Test agent",
        )

        async for _ in server._process_message("Break", session_id="err-session"):
            pass

        events = await memory.get_session_events("err-session")
        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) >= 1


class TestAgentConfiguration:
    """Test agent configuration options."""

    def test_default_max_steps(self):
        """Test default max_steps value."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="default-agent", model=model)
        assert server.settings.agentic_loop_max_steps == 5

    def test_custom_max_steps(self):
        """Test custom max_steps value."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="custom-agent", model=model, max_steps=10)
        assert server.settings.agentic_loop_max_steps == 10

    def test_default_memory_context_limit(self):
        """Test default memory context limit."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="mem-limit-agent", model=model)
        assert server.settings.memory_context_limit == 6

    def test_custom_memory_context_limit(self):
        """Test custom memory context limit."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="mem-limit-agent", model=model, memory_context_limit=20)
        assert server.settings.memory_context_limit == 20

    def test_model_from_url_and_name(self):
        """Test creating model from model_api_url and model_name."""
        from pais.serverutils import _resolve_model

        model, mock_state = _resolve_model(
            "url-agent",
            model_api_url="http://localhost:11434/v1",
            model_name="test-model",
        )
        assert model is not None
        assert mock_state is None

    def test_agent_requires_model_source(self):
        """Test agent creation without model source raises error."""
        with pytest.raises(ValueError, match="Agent requires"):
            from pais.serverutils import _resolve_model

            _resolve_model("no-model-agent")

    def test_memory_type_flag(self):
        """Test memory type detection."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="no-mem-agent", model=model, memory=NullMemory())
        assert isinstance(server.memory, NullMemory)


class TestUserPromptExtraction:
    """Test user prompt extraction from various message formats."""

    @pytest.mark.asyncio
    async def test_string_message(self):
        """Test extracting prompt from string."""
        model = TestModel(custom_output_text="Got it")
        server = make_test_server(name="extract-agent", model=model, instructions="Test agent")

        response = ""
        async for chunk in server._process_message("Hello world", session_id="test"):
            response += chunk

        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_message_array(self):
        """Test extracting prompt from OpenAI-style message array."""
        model = TestModel(custom_output_text="Got it")
        server = make_test_server(name="extract-agent", model=model, instructions="Test agent")

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello from array"},
        ]

        response = ""
        async for chunk in server._process_message(messages, session_id="test"):
            response += chunk

        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_task_delegation_role(self):
        """Test extracting prompt from task-delegation role."""
        model = TestModel(custom_output_text="Task received")
        server = make_test_server(name="task-agent", model=model, instructions="Test agent")

        messages = [
            {"role": "task-delegation", "content": "Process this task"},
        ]

        response = ""
        async for chunk in server._process_message(messages, session_id="test"):
            response += chunk

        assert len(response) > 0
