"""
Agentic Loop tests with deterministic mock responses.

Tests the agentic loop functionality including:
- Tool calling via native OpenAI function calling
- Agent delegation via delegate_to_{name} tool functions
- Memory event verification
- Max steps limit
"""

import pytest
import logging
import time
from multiprocessing import Process
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock

from agent.client import Agent, RemoteAgent, DELEGATION_TOOL_PREFIX
from agent.memory import LocalMemory
from agent.server import AgentServerSettings, create_agent_server
from modelapi.client import ModelAPI, ModelResponse, ToolCall
from mcptools.client import MCPClient, Tool

logger = logging.getLogger(__name__)


def _make_native_agent(**kwargs) -> Agent:
    """Create an Agent with native tool calling enabled (for testing)."""
    agent = Agent(**kwargs)
    agent._supports_native_tools = True
    return agent


class MockModelAPI(ModelAPI):
    """Mock ModelAPI that returns predetermined responses.

    Responses can be:
    - str: returned as ModelResponse(content=str)
    - ModelResponse: returned directly
    """

    def __init__(self, responses: Optional[list] = None):
        """Initialize with a list of responses to return in sequence."""
        self.responses = list(responses) if responses else ["Default mock response"]
        self._responses_original = list(self.responses)  # Keep original for reset
        self.call_count = 0
        self.model = "mock"
        self.api_base = "mock://localhost"
        self.client = None  # Not used
        self._mock_responses_template: Optional[List[str]] = None  # Not used in mock

    def reset_mock_responses(self) -> None:
        """Reset mock responses to start a fresh cycle."""
        self.responses = list(self._responses_original)
        self.call_count = 0

    @property
    def has_mock_responses(self) -> bool:
        """Check if mock responses are configured."""
        return bool(self._responses_original)

    async def process_message(self, messages, stream=False, seed: Optional[int] = None, tools=None):
        """Return next response from the list.

        Returns ModelResponse if stream=False, AsyncIterator[str] if stream=True.
        """
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        if stream:
            content = resp.content if isinstance(resp, ModelResponse) else resp
            return self._yield_content(content or "")
        if isinstance(resp, ModelResponse):
            return resp
        return ModelResponse(content=resp, finish_reason="stop")

    async def _yield_content(self, content: str):
        """Yield content as streaming chunks."""
        for word in content.split():
            yield word + " "

    async def close(self):
        pass


class MockMCPClient(MCPClient):
    """Mock MCP client with predefined tools."""

    def __init__(self, tools: Optional[dict] = None):
        """Initialize with tool definitions: {name: (description, result)}"""
        self._mcp_url = "mock://mcp"
        self._tools = {}
        self._active = True  # Always active for mocks
        self.call_log = []

        tools = tools or {}
        for name, (desc, result) in tools.items():
            self._tools[name] = Tool(
                name=name,
                description=desc,
                input_schema={"type": "object", "properties": {}},
            )
            setattr(self, f"_result_{name}", result)

    async def _init(self):
        return True

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None) -> Any:
        self.call_log.append({"tool": name, "args": args or {}})
        result = getattr(self, f"_result_{name}", {"result": "ok"})
        return result

    def get_tools(self):
        return list(self._tools.values())

    async def close(self):
        pass


class TestMaxStepsConfig:
    """Tests for max_steps configuration."""

    def test_default_max_steps(self):
        """Test default max_steps value."""
        model_api = MockModelAPI(["test"])
        agent = Agent(name="test", model_api=model_api)
        assert agent.max_steps == 5

    def test_custom_max_steps(self):
        """Test custom max_steps value."""
        model_api = MockModelAPI(["test"])
        agent = Agent(name="test", model_api=model_api, max_steps=3)
        assert agent.max_steps == 3

    def test_max_steps_zero_allowed(self):
        """Test that max_steps=0 is allowed (skips Phase 1 reasoning)."""
        model_api = MockModelAPI(["test"])
        agent = Agent(name="test", model_api=model_api, max_steps=0)
        assert agent.max_steps == 0

    def test_max_steps_negative_allowed(self):
        """Test that negative max_steps is allowed (skips Phase 1 reasoning)."""
        model_api = MockModelAPI(["test"])
        agent = Agent(name="test", model_api=model_api, max_steps=-5)
        assert agent.max_steps == -5


class TestAgenticLoopToolCalling:
    """Tests for tool calling in the agentic loop."""

    @pytest.mark.asyncio
    async def test_tool_call_detected_and_executed(self):
        """Test that a tool call in model response triggers tool execution."""
        # Native function calling: model returns tool_calls, then no-tool break, then final
        tool_call_response = ModelResponse(
            tool_calls=[ToolCall(id="call_1", name="calculator", arguments={"a": 5, "b": 3})],
            finish_reason="tool_calls",
        )
        loop_break = ModelResponse(content=None, finish_reason="stop")
        final_response = "The result is 8."

        mock_model = MockModelAPI(responses=[tool_call_response, loop_break, final_response])
        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        # Process message
        result = []
        async for chunk in agent.process_message("What is 5 + 3?"):
            result.append(chunk)

        response = "".join(result)

        # Verify tool was called
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "calculator"

        # Verify model was called: tool_call → loop break → Phase 2 final
        assert mock_model.call_count == 3

        # Verify memory has tool events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]

        assert "user_message" in event_types
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert "agent_response" in event_types

        logger.info("✓ Tool call detection and execution works")

    @pytest.mark.asyncio
    async def test_tool_call_with_arguments(self):
        """Test that tool calls pass arguments correctly."""
        tool_call_response = ModelResponse(
            tool_calls=[ToolCall(id="call_1", name="calculator", arguments={"a": 5, "b": 3})],
            finish_reason="tool_calls",
        )
        loop_break = ModelResponse(content=None, finish_reason="stop")
        final_response = "The result is 8."

        mock_model = MockModelAPI(responses=[tool_call_response, loop_break, final_response])
        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("What is 5 + 3?"):
            result.append(chunk)

        # Verify tool was called with correct arguments
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "calculator"
        assert mock_mcp.call_log[0]["args"] == {"a": 5, "b": 3}

        logger.info("✓ Tool call with arguments works")

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_parallel(self):
        """Test that multiple tool calls in a single response are executed in parallel."""
        tool_call_response = ModelResponse(
            tool_calls=[
                ToolCall(id="call_1", name="calculator", arguments={"a": 1, "b": 2}),
                ToolCall(id="call_2", name="echo", arguments={"message": "hi"}),
            ],
            finish_reason="tool_calls",
        )
        loop_break = ModelResponse(content=None, finish_reason="stop")
        final_response = "Calculated 3 and echoed hi."

        mock_model = MockModelAPI(responses=[tool_call_response, loop_break, final_response])
        mock_mcp = MockMCPClient(
            tools={
                "calculator": ("Add two numbers", {"sum": 3}),
                "echo": ("Echo a message", {"echo": "hi"}),
            }
        )
        memory = LocalMemory()

        agent = _make_native_agent(
            name="multi-tool",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("Calculate 1+2 and echo hi"):
            result.append(chunk)

        # Both tools should have been called
        assert len(mock_mcp.call_log) == 2
        tool_names = {c["tool"] for c in mock_mcp.call_log}
        assert tool_names == {"calculator", "echo"}

        # Model called 3 times: tool_calls → loop break → Phase 2 final
        assert mock_model.call_count == 3

        # Memory should have both tool_call and tool_result events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        tool_call_events = [e for e in events if e.event_type == "tool_call"]
        tool_result_events = [e for e in events if e.event_type == "tool_result"]
        assert len(tool_call_events) == 2
        assert len(tool_result_events) == 2

        logger.info("✓ Multiple parallel tool calls work")


class TestAgenticLoopDelegation:
    """Tests for agent delegation in the agentic loop."""

    @pytest.mark.asyncio
    async def test_delegation_detected_and_executed(self):
        """Test that a delegation tool call triggers sub-agent invocation."""
        # Native function calling: model calls delegate_to_worker tool
        delegation_response = ModelResponse(
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="delegate_to_worker",
                    arguments={"task": "Process this data"},
                )
            ],
            finish_reason="tool_calls",
        )
        loop_break = ModelResponse(content=None, finish_reason="stop")
        final_response = "The worker processed the data successfully."

        mock_model = MockModelAPI(responses=[delegation_response, loop_break, final_response])
        memory = LocalMemory()

        # Create mock remote agent
        mock_remote = RemoteAgent(name="worker", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "worker",
                "description": "Worker agent",
                "url": "http://localhost:9999",
                "capabilities": ["task_execution"],
            },
        )()
        mock_remote._active = True
        mock_remote.process_message = AsyncMock(return_value="Data processed")  # type: ignore[method-assign]

        agent = _make_native_agent(
            name="coordinator",
            model_api=mock_model,
            sub_agents=[mock_remote],
            memory=memory,
            max_steps=5,
        )

        # Process message
        result = []
        async for chunk in agent.process_message("Process the data"):
            result.append(chunk)

        # Verify delegation occurred - process_message now receives messages list
        mock_remote.process_message.assert_called_once()  # type: ignore[union-attr]
        call_args = mock_remote.process_message.call_args[0][0]  # type: ignore[union-attr]
        assert isinstance(call_args, list)
        # Last message should be task-delegation with the task
        assert call_args[-1]["role"] == "task-delegation"
        assert "Process this data" in call_args[-1]["content"]

        # Verify model calls: delegation tool_call → loop break → Phase 2 final
        assert mock_model.call_count == 3

        # Verify memory has delegation events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]

        assert "delegation_request" in event_types
        assert "delegation_response" in event_types

        # Verify tool_call event emitted before delegation_request (symmetry with regular tools)
        tool_call_events = [e for e in events if e.event_type == "tool_call"]
        delegation_events = [e for e in events if e.event_type == "delegation_request"]
        assert len(tool_call_events) >= 1
        assert len(delegation_events) == 1
        # The delegation tool_call should reference the delegate_to_ tool
        delegation_tool_call = [e for e in tool_call_events if "delegate_to_" in str(e.content)]
        assert len(delegation_tool_call) == 1

        logger.info("✓ Delegation detection and execution works")


class TestAgenticLoopMaxSteps:
    """Tests for max steps limit."""

    @pytest.mark.asyncio
    async def test_max_steps_prevents_infinite_loop(self):
        """Test that max_steps prevents infinite tool call loops."""
        # Model always returns a tool call
        infinite_tool_call = ModelResponse(
            tool_calls=[ToolCall(id="call_1", name="loop_tool", arguments={})],
            finish_reason="tool_calls",
        )

        mock_model = MockModelAPI(responses=[infinite_tool_call] * 10)
        mock_mcp = MockMCPClient(tools={"loop_tool": ("Loops forever", {"result": "ok"})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="loop-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=3,
        )

        result = []
        async for chunk in agent.process_message("Start loop"):
            result.append(chunk)

        response = "".join(result)

        # Should hit max steps limit
        assert "maximum reasoning steps" in response.lower()

        # Tool should be called max_steps times
        assert len(mock_mcp.call_log) == 3

        logger.info("✓ Max steps limit works")

    @pytest.mark.asyncio
    async def test_no_tools_skips_phase1(self):
        """Test that agent with no tools/agents skips Phase 1 entirely."""
        mock_model = MockModelAPI(responses=["Direct response."])
        memory = LocalMemory()

        agent = Agent(
            name="simple-agent",
            model_api=mock_model,
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("Hello"):
            result.append(chunk)

        response = "".join(result)
        assert "Direct response." in response
        # Only 1 model call for Phase 2 (Phase 1 skipped)
        assert mock_model.call_count == 1

        logger.info("✓ No tools skips Phase 1")

    @pytest.mark.asyncio
    async def test_max_steps_zero_skips_phase1(self):
        """Test that max_steps=0 skips Phase 1 even with tools available."""
        mock_model = MockModelAPI(responses=["Direct response."])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo tool", {"result": "ok"})})
        memory = LocalMemory()

        agent = Agent(
            name="no-reasoning-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=0,
        )

        result = []
        async for chunk in agent.process_message("Hello"):
            result.append(chunk)

        response = "".join(result)
        assert "Direct response." in response
        # Only 1 model call for Phase 2 (Phase 1 skipped due to max_steps=0)
        assert mock_model.call_count == 1
        # No tools should have been called
        assert len(mock_mcp.call_log) == 0

        logger.info("✓ max_steps=0 skips Phase 1")


class TestMemoryContextLimit:
    """Tests for configurable memory context limit."""

    @pytest.mark.asyncio
    async def test_default_memory_context_limit(self):
        """Test default memory_context_limit value."""
        mock_model = MockModelAPI(["test"])
        agent = Agent(name="test", model_api=mock_model)
        assert agent.memory_context_limit == 6

    @pytest.mark.asyncio
    async def test_custom_memory_context_limit(self):
        """Test custom memory_context_limit value."""
        mock_model = MockModelAPI(["test"])
        agent = Agent(name="test", model_api=mock_model, memory_context_limit=10)
        assert agent.memory_context_limit == 10

    @pytest.mark.asyncio
    async def test_delegation_respects_memory_context_limit(self):
        """Test that delegation uses memory_context_limit to limit context messages."""
        delegation_response = ModelResponse(
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="delegate_to_worker",
                    arguments={"task": "Do the work"},
                )
            ],
            finish_reason="tool_calls",
        )
        final_response = "Done."

        mock_model = MockModelAPI(
            responses=[
                delegation_response,
                ModelResponse(content=None, finish_reason="stop"),
                final_response,
            ]
        )
        memory = LocalMemory()

        # Create mock remote agent
        mock_remote = RemoteAgent(name="worker", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {"name": "worker", "description": "Worker", "url": "http://localhost:9999"},
        )()
        mock_remote._active = True
        mock_remote.process_message = AsyncMock(return_value="Work done")  # type: ignore[method-assign]

        # Create agent with custom memory context limit of 2
        agent = _make_native_agent(
            name="coordinator",
            model_api=mock_model,
            sub_agents=[mock_remote],
            memory=memory,
            memory_context_limit=2,
        )

        # Process message
        result = []
        async for chunk in agent.process_message("Do some work"):
            result.append(chunk)

        # Verify delegation occurred
        mock_remote.process_message.assert_called_once()  # type: ignore[union-attr]
        call_args = mock_remote.process_message.call_args[0][0]  # type: ignore[union-attr]

        # Should have at most memory_context_limit + 1 messages (context + task-delegation)
        # With limit=2, we expect: up to 2 context messages + 1 task-delegation message
        assert len(call_args) <= 3

        # Last message should always be task-delegation
        assert call_args[-1]["role"] == "task-delegation"

        logger.info("✓ Memory context limit works for delegation")


class TestSystemPromptBuilding:
    """Tests for system prompt construction and tools parameter building."""

    @pytest.mark.asyncio
    async def test_tools_param_includes_mcp_tools(self):
        """Test that _build_tools_param includes available MCP tools."""
        mock_model = MockModelAPI(responses=["I have tools available."])
        mock_mcp = MockMCPClient(
            tools={
                "search": ("Search for information", {}),
                "calculate": ("Perform calculations", {}),
            }
        )

        agent = Agent(
            name="tools-agent",
            instructions="You are a helpful agent.",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
        )

        tools = await agent._build_tools_param()
        assert tools is not None
        assert len(tools) == 2

        tool_names = [t["function"]["name"] for t in tools]
        assert "search" in tool_names
        assert "calculate" in tool_names

        # Verify OpenAI format
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

        logger.info("✓ Tools param includes MCP tools")

    @pytest.mark.asyncio
    async def test_tools_param_includes_delegation_tools(self):
        """Test that _build_tools_param includes delegation tools for sub-agents."""
        mock_model = MockModelAPI(responses=["I can delegate."])

        mock_remote = RemoteAgent(name="worker", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "worker",
                "description": "Worker that processes tasks",
                "url": "http://localhost:9999",
                "capabilities": ["task_execution"],
            },
        )()
        mock_remote._active = True

        agent = Agent(
            name="coordinator",
            instructions="You coordinate work.",
            model_api=mock_model,
            sub_agents=[mock_remote],
        )

        tools = await agent._build_tools_param()
        assert tools is not None
        assert len(tools) == 1

        delegation_tool = tools[0]
        assert delegation_tool["function"]["name"] == "delegate_to_worker"
        assert "task" in delegation_tool["function"]["parameters"]["properties"]

        logger.info("✓ Tools param includes delegation tools")

    @pytest.mark.asyncio
    async def test_unavailable_sub_agents_excluded_from_tools(self):
        """Test that unavailable sub-agents are not registered as tools."""
        mock_model = MockModelAPI(responses=["test"])

        active_remote = RemoteAgent(name="active-worker", card_url="http://localhost:9999")
        active_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "active-worker",
                "description": "Active worker",
                "url": "http://localhost:9999",
                "capabilities": [],
            },
        )()
        active_remote._active = True

        inactive_remote = RemoteAgent(name="dead-worker", card_url="http://localhost:9998")
        inactive_remote._active = False

        agent = Agent(
            name="coordinator",
            model_api=mock_model,
            sub_agents=[active_remote, inactive_remote],
        )

        tools = await agent._build_tools_param()
        assert tools is not None
        tool_names = [t["function"]["name"] for t in tools]
        assert "delegate_to_active-worker" in tool_names
        assert "delegate_to_dead-worker" not in tool_names

        logger.info("✓ Unavailable sub-agents excluded from tools")

    @pytest.mark.asyncio
    async def test_system_prompt_includes_user_provided_prompt(self):
        """Test that system prompt includes user-provided system prompt."""
        mock_model = MockModelAPI(responses=["Response with user context."])

        agent = Agent(
            name="test-agent",
            instructions="You are a helpful agent.",
            model_api=mock_model,
        )

        # Build prompt with user-provided system prompt
        prompt = await agent._build_system_prompt("Always respond in JSON format.")

        # Check agent system prompt is included
        assert "## Agent System Prompt" in prompt
        assert "You are a helpful agent." in prompt

        # Check user-provided system prompt is included
        assert "## User-Provided System Prompt" in prompt
        assert "Always respond in JSON format." in prompt

        # Check precedence note is included
        assert "Agent System Prompt takes precedence" in prompt

        logger.info("✓ System prompt includes user-provided prompt")

    @pytest.mark.asyncio
    async def test_process_message_merges_user_system_prompt(self):
        """Test that process_message correctly merges user system prompts."""
        mock_model = MockModelAPI(responses=["Response considering user context."])

        agent = Agent(
            name="test-agent",
            instructions="You are a helpful agent.",
            model_api=mock_model,
        )

        # Send message with user-provided system prompt
        result = []
        async for chunk in agent.process_message(
            [
                {"role": "system", "content": "Always be concise."},
                {"role": "user", "content": "Hello"},
            ]
        ):
            result.append(chunk)

        # Verify result
        assert len(result) > 0
        assert mock_model.call_count == 1  # No tools → Phase 1 skipped, Phase 2 only

        logger.info("✓ Process message merges user system prompt")


class TestMockResponseEnvVar:
    """Tests for the DEBUG_MOCK_RESPONSES environment variable."""

    @pytest.mark.asyncio
    async def test_mock_responses_env_var_bypasses_model(self):
        """Test that DEBUG_MOCK_RESPONSES env var bypasses the actual model call."""
        import os
        import json

        memory = LocalMemory()

        # Set mock responses via env var BEFORE creating ModelAPI
        # No tools → Phase 1 skipped, only Phase 2 response needed
        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(["Mocked response from env"])

        try:
            # Use real ModelAPI - it reads env var in __init__
            model_api = ModelAPI(model="test", api_base="http://localhost:9999")

            agent = Agent(name="mock-test", model_api=model_api, memory=memory)

            result = []
            async for chunk in agent.process_message("Hello"):
                result.append(chunk)

            response = "".join(result)

            # Should get mock response
            assert "Mocked response from env" in response

            await model_api.close()
            logger.info("✓ Mock response env var works")
        finally:
            # Clean up
            del os.environ["DEBUG_MOCK_RESPONSES"]

    @pytest.mark.asyncio
    async def test_mock_responses_array_for_agentic_loop(self):
        """Test that DEBUG_MOCK_RESPONSES array supports multi-step agentic loop."""
        import os
        import json

        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        # Mock responses: tool call → loop break (no tool_calls) → final response
        mock_responses = [
            json.dumps(
                {
                    "tool_calls": [
                        {"id": "call_1", "name": "calculator", "arguments": {"a": 5, "b": 3}}
                    ]
                }
            ),
            "No more tools needed.",
            "The result is 8.",
        ]
        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(mock_responses)

        try:
            # Use real ModelAPI - it reads env var in __init__
            model_api = ModelAPI(model="test", api_base="http://localhost:9999")

            agent = _make_native_agent(
                name="mock-test",
                model_api=model_api,
                mcp_clients=[mock_mcp],
                memory=memory,
                max_steps=5,
            )

            result = []
            async for chunk in agent.process_message("What is 5 + 3?"):
                result.append(chunk)

            response = "".join(result)

            # Should get final response after tool call (may include progress blocks)
            assert "8" in response

            # Tool should have been called
            assert len(mock_mcp.call_log) == 1

            await model_api.close()
            logger.info("✓ Mock response array works for agentic loop")
        finally:
            # Clean up
            del os.environ["DEBUG_MOCK_RESPONSES"]


class TestMemoryEventTracking:
    """Tests for memory event tracking during agentic loop."""

    @pytest.mark.asyncio
    async def test_complete_workflow_memory_tracking(self):
        """Test that all events are properly tracked in memory."""
        # Workflow: tool call -> delegation -> final response
        tool_call_response = ModelResponse(
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="fetch",
                    arguments={"url": "http://example.com"},
                )
            ],
            finish_reason="tool_calls",
        )
        delegation_response = ModelResponse(
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="delegate_to_analyzer",
                    arguments={"task": "Analyze the data"},
                )
            ],
            finish_reason="tool_calls",
        )
        final_response = "Based on my analysis, the result is complete."

        mock_model = MockModelAPI(
            responses=[
                tool_call_response,
                delegation_response,
                ModelResponse(content=None, finish_reason="stop"),
                final_response,
            ]
        )
        mock_mcp = MockMCPClient(tools={"fetch": ("Fetch URL", {"data": "example"})})

        mock_remote = RemoteAgent(name="analyzer", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "analyzer",
                "description": "Analyzer",
                "url": "http://localhost:9999",
                "capabilities": [],
            },
        )()
        mock_remote._active = True
        mock_remote.process_message = AsyncMock(return_value="Analysis complete")  # type: ignore[method-assign]

        memory = LocalMemory()

        agent = _make_native_agent(
            name="workflow-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            sub_agents=[mock_remote],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("Complete the workflow"):
            result.append(chunk)

        # Get all events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]

        # Should have full event chain
        assert "user_message" in event_types
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert "delegation_request" in event_types
        assert "delegation_response" in event_types
        assert "agent_response" in event_types

        # Verify event order
        user_idx = event_types.index("user_message")
        tool_idx = event_types.index("tool_call")
        delegation_idx = event_types.index("delegation_request")
        response_idx = event_types.index("agent_response")

        assert user_idx < tool_idx < delegation_idx < response_idx

        logger.info("✓ Complete workflow memory tracking works")


class TestFormatWarnings:
    """Tests for format warning logging and memory events."""

    @pytest.mark.asyncio
    async def test_empty_response_stores_format_warning(self):
        """Test that empty model response (no content, no tool_calls) stores format warning."""
        # Model returns empty response (no content, no tool_calls), then final response
        empty_response = ModelResponse(content=None, finish_reason="stop")
        final_response = "Here is my response."

        mock_model = MockModelAPI(responses=[empty_response, final_response])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo tool", {"result": "ok"})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="warn-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("test"):
            result.append(chunk)

        # Verify format_warning was stored in memory
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]

        assert "format_warning" in event_types
        warning_event = next(e for e in events if e.event_type == "format_warning")
        assert "empty response" in warning_event.content.lower()

        logger.info("✓ Empty response format warning works")

    @pytest.mark.asyncio
    async def test_empty_response_logs_warning(self, caplog):
        """Test that empty model response logs a warning."""
        empty_response = ModelResponse(content=None, finish_reason="stop")
        final_response = "Here is my response."

        mock_model = MockModelAPI(responses=[empty_response, final_response])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo tool", {"result": "ok"})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="warn-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        with caplog.at_level(logging.WARNING, logger="agent.client"):
            result = []
            async for chunk in agent.process_message("test"):
                result.append(chunk)

        assert any("no tool_calls and no content" in r.message for r in caplog.records)

        logger.info("✓ Empty response warning logging works")


class TestPhase2FinalResponse:
    """Tests for Phase 2 always calling model with final-response instruction."""

    @pytest.mark.asyncio
    async def test_phase2_always_calls_model_for_final_response(self):
        """Test that Phase 2 always calls model even when Phase 1 had content."""
        # Phase 1: model returns content (no tool calls) → breaks loop
        # Phase 2: must call model again with final-response instruction
        phase1_response = ModelResponse(content="Intermediate thought.", finish_reason="stop")
        final_response = "Final synthesized answer."

        mock_model = MockModelAPI(responses=[phase1_response, final_response])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo tool", {"result": "ok"})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="phase2-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("test"):
            result.append(chunk)

        response = "".join(result)
        assert "Final synthesized answer." in response

        # Model called twice: Phase 1 (no tool_calls, breaks) → Phase 2 (final response)
        assert mock_model.call_count == 2

        logger.info("✓ Phase 2 always calls model for final response")

    @pytest.mark.asyncio
    async def test_phase2_streaming_calls_model(self):
        """Test that streaming Phase 2 calls model (not reusing Phase 1 content)."""
        phase1_response = ModelResponse(content="Thinking...", finish_reason="stop")
        streaming_final = "Streamed final answer."

        mock_model = MockModelAPI(responses=[phase1_response, streaming_final])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo tool", {"result": "ok"})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="stream-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("test", stream=True):
            result.append(chunk)

        # Model called twice: Phase 1 (non-streaming) + Phase 2 (streaming)
        assert mock_model.call_count == 2

        logger.info("✓ Phase 2 streaming calls model")

    @pytest.mark.asyncio
    async def test_phase2_after_tool_calls(self):
        """Test Phase 2 after tool execution calls model with final instruction."""
        tool_call_response = ModelResponse(
            tool_calls=[ToolCall(id="call_1", name="echo", arguments={"msg": "hi"})],
            finish_reason="tool_calls",
        )
        # Phase 1 second call: no tool_calls → break
        no_tool_response = ModelResponse(content=None, finish_reason="stop")
        final_response = "Based on the tool results, here is my answer."

        mock_model = MockModelAPI(responses=[tool_call_response, no_tool_response, final_response])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo", {"echo": "hi"})})
        memory = LocalMemory()

        agent = _make_native_agent(
            name="tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("test"):
            result.append(chunk)

        response = "".join(result)
        assert "Based on the tool results" in response

        # Model called 3 times: tool_call → no_tool → final
        assert mock_model.call_count == 3

        logger.info("✓ Phase 2 after tool calls works")


class TestToolCallArgumentNormalization:
    """Tests for ToolCall argument handling consistency."""

    def test_toolcall_dict_arguments(self):
        """Test ToolCall with dict arguments."""
        tc = ToolCall(id="1", name="test", arguments={"key": "value"})
        assert tc.arguments == {"key": "value"}

    def test_toolcall_string_arguments_parsed(self):
        """Test ToolCall with JSON string arguments auto-parsed to dict."""
        tc = ToolCall(id="1", name="test", arguments='{"key": "value"}')
        assert tc.arguments == {"key": "value"}

    def test_toolcall_invalid_string_arguments(self):
        """Test ToolCall with invalid JSON string defaults to empty dict."""
        tc = ToolCall(id="1", name="test", arguments="not json")
        assert tc.arguments == {}

    def test_toolcall_invalid_string_arguments_logs_warning(self, caplog):
        """Test ToolCall with invalid JSON string logs a warning."""
        with caplog.at_level(logging.WARNING, logger="modelapi.client"):
            ToolCall(id="1", name="test", arguments="bad json")
        assert any("Malformed tool call arguments" in r.message for r in caplog.records)

    def test_toolcall_from_openai_string_arguments(self):
        """Test from_openai with JSON string arguments."""
        tc = ToolCall.from_openai(
            {
                "id": "call_1",
                "function": {"name": "echo", "arguments": '{"msg": "hi"}'},
            }
        )
        assert tc.arguments == {"msg": "hi"}

    def test_toolcall_from_openai_dict_arguments(self):
        """Test from_openai with already-parsed dict arguments."""
        tc = ToolCall.from_openai(
            {
                "id": "call_1",
                "function": {"name": "echo", "arguments": {"msg": "hi"}},
            }
        )
        assert tc.arguments == {"msg": "hi"}


class TestStringModeToolCalling:
    """Tests for string-mode tool calling in the agentic loop."""

    @pytest.mark.asyncio
    async def test_string_mode_tool_call(self):
        """Test that string mode parses tool call JSON from content."""
        tool_response = ModelResponse(
            content='I will use the calculator. {"tool": "calculator", "arguments": {"a": 5, "b": 3}}',
            finish_reason="stop",
        )
        no_action_response = ModelResponse(content="No more actions needed.", finish_reason="stop")
        final_response = "The result is 8."

        mock_model = MockModelAPI(responses=[tool_response, no_action_response, final_response])
        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        agent = Agent(
            name="string-tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )
        agent._supports_native_tools = False

        result = []
        async for chunk in agent.process_message("What is 5 + 3?"):
            result.append(chunk)

        # Verify tool was called
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "calculator"
        assert mock_mcp.call_log[0]["args"] == {"a": 5, "b": 3}

        # Verify memory has tool events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]
        assert "tool_call" in event_types
        assert "tool_result" in event_types

        logger.info("✓ String mode tool call works")

    @pytest.mark.asyncio
    async def test_string_mode_delegation(self):
        """Test that string mode parses delegation JSON from content."""
        delegation_response = ModelResponse(
            content='I will delegate. {"tool": "delegate_to_worker", "arguments": {"task": "Process this data"}}',
            finish_reason="stop",
        )
        no_action_response = ModelResponse(content="No more actions.", finish_reason="stop")
        final_response = "The worker processed the data."

        mock_model = MockModelAPI(
            responses=[delegation_response, no_action_response, final_response]
        )
        memory = LocalMemory()

        mock_remote = RemoteAgent(name="worker", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "worker",
                "description": "Worker agent",
                "url": "http://localhost:9999",
                "capabilities": ["task_execution"],
            },
        )()
        mock_remote._active = True
        mock_remote.process_message = AsyncMock(return_value="Data processed")  # type: ignore[method-assign]

        agent = Agent(
            name="coordinator",
            model_api=mock_model,
            sub_agents=[mock_remote],
            memory=memory,
            max_steps=5,
        )
        agent._supports_native_tools = False

        result = []
        async for chunk in agent.process_message("Process the data"):
            result.append(chunk)

        # Verify delegation occurred
        mock_remote.process_message.assert_called_once()  # type: ignore[union-attr]

        # Verify memory events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]
        assert "delegation_request" in event_types
        assert "delegation_response" in event_types

        logger.info("✓ String mode delegation works")

    @pytest.mark.asyncio
    async def test_string_mode_no_action_breaks_loop(self):
        """Test that content without tool JSON breaks the string-mode loop."""
        no_action = ModelResponse(content="I have nothing to do.", finish_reason="stop")
        final_response = "Here is my answer."

        mock_model = MockModelAPI(responses=[no_action, final_response])
        mock_mcp = MockMCPClient(tools={"echo": ("Echo", {"result": "ok"})})
        memory = LocalMemory()

        agent = Agent(
            name="string-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )
        agent._supports_native_tools = False

        result = []
        async for chunk in agent.process_message("Hello"):
            result.append(chunk)

        response = "".join(result)
        assert "Here is my answer." in response
        assert len(mock_mcp.call_log) == 0

        logger.info("✓ String mode no-action breaks loop")

    @pytest.mark.asyncio
    async def test_string_mode_system_prompt_includes_tools(self):
        """Test that string mode builds system prompt with tool descriptions."""
        mock_model = MockModelAPI(responses=["Response"])
        mock_mcp = MockMCPClient(tools={"search": ("Search for info", {})})

        agent = Agent(
            name="string-tools-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
        )
        agent._supports_native_tools = False

        prompt = await agent._build_system_prompt()
        assert "## Available Tools" in prompt
        assert "search" in prompt
        assert '{"tool": "tool_name"' in prompt

        logger.info("✓ String mode system prompt includes tools")

    @pytest.mark.asyncio
    async def test_string_mode_max_steps_limit(self):
        """Test that max_steps is respected in string mode."""
        tool_action = ModelResponse(
            content='{"tool": "loop_tool", "arguments": {}}',
            finish_reason="stop",
        )

        mock_model = MockModelAPI(responses=[tool_action] * 10)
        mock_mcp = MockMCPClient(tools={"loop_tool": ("Loops forever", {"result": "ok"})})
        memory = LocalMemory()

        agent = Agent(
            name="loop-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=3,
        )
        agent._supports_native_tools = False

        result = []
        async for chunk in agent.process_message("Start loop"):
            result.append(chunk)

        response = "".join(result)
        assert "maximum reasoning steps" in response.lower()
        assert len(mock_mcp.call_log) == 3

        logger.info("✓ String mode max steps limit works")


class TestParseAction:
    """Tests for the _parse_action method used in string mode."""

    def setup_method(self):
        mock_model = MockModelAPI(["test"])
        self.agent = Agent(name="test", model_api=mock_model)

    def test_parse_pure_json(self):
        """Test parsing pure JSON content."""
        result = self.agent._parse_action('{"tool": "echo", "arguments": {"msg": "hi"}}')
        assert result == {"tool": "echo", "arguments": {"msg": "hi"}}

    def test_parse_json_in_text(self):
        """Test parsing JSON embedded in text."""
        result = self.agent._parse_action(
            'I will use the tool. {"tool": "calc", "arguments": {"a": 1}} Great.'
        )
        assert result is not None
        assert result["tool"] == "calc"

    def test_parse_no_tool_key(self):
        """Test parsing JSON without tool key returns None."""
        result = self.agent._parse_action("No more actions needed. {}")
        assert result is None

    def test_parse_no_json(self):
        """Test parsing content with no JSON returns None."""
        result = self.agent._parse_action("Just a plain text response.")
        assert result is None

    def test_parse_delegation(self):
        """Test parsing delegation action uses delegate_to_ format."""
        result = self.agent._parse_action(
            '{"tool": "delegate_to_worker", "arguments": {"task": "do something"}}'
        )
        assert result is not None
        assert result["tool"] == "delegate_to_worker"
        assert result["arguments"]["task"] == "do something"

    def test_parse_nested_json(self):
        """Test parsing JSON with nested objects."""
        result = self.agent._parse_action(
            '{"tool": "search", "arguments": {"query": "test", "options": {"limit": 10}}}'
        )
        assert result is not None
        assert result["tool"] == "search"
        assert result["arguments"]["options"]["limit"] == 10
