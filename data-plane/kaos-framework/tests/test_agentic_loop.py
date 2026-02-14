"""
Agentic Loop tests with deterministic mock responses.

Tests the agentic loop functionality including:
- Tool calling with mock responses
- Agent delegation with mock responses
- Memory event verification
- Max steps limit
"""

import pytest
import logging
import time
import httpx
from multiprocessing import Process
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock

from agent.client import Agent, RemoteAgent
from agent.memory import LocalMemory
from agent.server import AgentServerSettings, create_agent_server
from modelapi.client import ModelAPI, ModelResponse, ToolCall
from mcptools.client import MCPClient, Tool

logger = logging.getLogger(__name__)


class MockModelAPI(ModelAPI):
    """Mock ModelAPI that returns predetermined responses."""

    def __init__(self, responses: Optional[list] = None):
        """Initialize with a list of responses to return in sequence."""
        self.responses = list(responses) if responses else ["Default mock response"]
        self._responses_original = list(self.responses)  # Keep original for reset
        self.call_count = 0
        self.model = "mock"
        self.api_base = "mock://localhost"
        self.client = None  # Not used
        self._mock_responses_template: Optional[List[str]] = None  # Not used in mock
        self.last_tools: Optional[List[dict]] = None
        self.all_tools_calls: List[Optional[List[dict]]] = []

    def reset_mock_responses(self) -> None:
        """Reset mock responses to start a fresh cycle."""
        self.responses = list(self._responses_original)
        self.call_count = 0

    @property
    def has_mock_responses(self) -> bool:
        """Check if mock responses are configured."""
        return bool(self._responses_original)

    async def process_message(
        self,
        messages,
        stream=False,
        seed: Optional[int] = None,
        tools: Optional[List[dict]] = None,
    ):
        """Return next response from the list.

        Returns ModelResponse if stream=False, AsyncIterator[str] if stream=True.
        Supports string, dict, and ModelResponse response formats.
        """
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        self.last_tools = tools
        self.all_tools_calls.append(tools)

        if stream:
            content = (
                response
                if isinstance(response, str)
                else (
                    response.content or "" if isinstance(response, ModelResponse) else str(response)
                )
            )
            return self._yield_content(content)

        # Return ModelResponse for non-streaming
        if isinstance(response, ModelResponse):
            return response
        if isinstance(response, dict):
            tool_calls = None
            if "tool_calls" in response:
                tool_calls = [
                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                    for tc in response["tool_calls"]
                ]
            return ModelResponse(content=response.get("content"), tool_calls=tool_calls)
        # Plain string: wrap in ModelResponse
        return ModelResponse(content=response)

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


class TestAgenticLoopToolCalling:
    """Tests for tool calling in the agentic loop."""

    @pytest.mark.asyncio
    async def test_tool_call_detected_and_executed(self):
        """Test that a tool call in model response triggers tool execution."""
        # Mock response with JSON action format
        # Two-phase loop: action -> (tool exec) -> no-action -> final response
        tool_call_response = '{"tool": "calculator", "arguments": {"a": 5, "b": 3}}'
        no_action_response = "{}"  # Signal to proceed to final response
        final_response = "The result is 8."

        mock_model = MockModelAPI(
            responses=[tool_call_response, no_action_response, final_response]
        )
        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        agent = Agent(
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

        # Verify model was called: action(tool) -> action(none) -> final response
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
    async def test_tool_call_with_context(self):
        """Test that tool calls work when model includes reasoning context."""
        # Model response with reasoning before JSON action
        tool_call_with_context = """I'll use the calculator to compute this sum.

{"tool": "calculator", "arguments": {"a": 5, "b": 3}}

Let me wait for the result."""
        no_action_response = "{}"
        final_response = "The result is 8."

        mock_model = MockModelAPI(
            responses=[tool_call_with_context, no_action_response, final_response]
        )
        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        agent = Agent(
            name="tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
        )

        result = []
        async for chunk in agent.process_message("What is 5 + 3?"):
            result.append(chunk)

        # Verify tool was called even with context around JSON
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "calculator"
        assert mock_model.call_count == 3

        logger.info("✓ Tool call with context works")


class TestAgenticLoopDelegation:
    """Tests for agent delegation in the agentic loop."""

    @pytest.mark.asyncio
    async def test_delegation_detected_and_executed(self):
        """Test that a delegation in model response triggers sub-agent invocation."""
        # JSON action format - two phase: action(delegate) -> action(none) -> final
        delegation_response = '{"agent": "worker", "task": "Process this data"}'
        no_action_response = "{}"
        final_response = "The worker processed the data successfully."

        mock_model = MockModelAPI(
            responses=[delegation_response, no_action_response, final_response]
        )
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
        # process_message now takes messages list, not just task string
        mock_remote.process_message = AsyncMock(return_value="Data processed")  # type: ignore[method-assign]

        agent = Agent(
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

        # Verify model calls: action(delegate) -> action(none) -> final response
        assert mock_model.call_count == 3

        # Verify memory has delegation events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]

        assert "delegation_request" in event_types
        assert "delegation_response" in event_types

        logger.info("✓ Delegation detection and execution works")


class TestAgenticLoopMaxSteps:
    """Tests for max steps limit."""

    @pytest.mark.asyncio
    async def test_max_steps_prevents_infinite_loop(self):
        """Test that max_steps prevents infinite tool call loops."""
        # JSON action format - model always returns a tool call
        infinite_tool_call = '{"tool": "loop_tool", "arguments": {}}'

        mock_model = MockModelAPI(responses=[infinite_tool_call] * 10)
        mock_mcp = MockMCPClient(tools={"loop_tool": ("Loops forever", {"result": "ok"})})
        memory = LocalMemory()

        agent = Agent(
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
        # JSON action format
        delegation_response = '{"agent": "worker", "task": "Do the work"}'
        final_response = "Done."

        mock_model = MockModelAPI(responses=[delegation_response, final_response])
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
        agent = Agent(
            name="coordinator",
            model_api=mock_model,
            sub_agents=[mock_remote],
            memory=memory,
            memory_context_limit=2,  # Only include last 2 messages
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
    """Tests for system prompt construction with tools and agents."""

    @pytest.mark.asyncio
    async def test_system_prompt_includes_tools(self):
        """Test that system prompt includes available tools."""
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

        prompt = await agent._build_system_prompt()

        assert "You are a helpful agent." in prompt
        assert "search" in prompt.lower()
        assert "calculate" in prompt.lower()
        # Check for JSON tool call format instruction
        assert '"tool":' in prompt

        logger.info("✓ System prompt includes tools")

    @pytest.mark.asyncio
    async def test_system_prompt_includes_agents(self):
        """Test that system prompt includes available sub-agents."""
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

        agent = Agent(
            name="coordinator",
            instructions="You coordinate work.",
            model_api=mock_model,
            sub_agents=[mock_remote],
        )

        prompt = await agent._build_system_prompt()

        assert "You coordinate work." in prompt
        assert "worker" in prompt.lower()
        assert "delegate" in prompt.lower()

        logger.info("✓ System prompt includes agents")

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
        # Two-phase: no-action (empty response) -> final response
        mock_model = MockModelAPI(responses=["{}", "Response considering user context."])

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

        # Verify the model was called: action check + final response
        assert len(result) > 0
        assert mock_model.call_count == 2

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
        # Two-phase loop: action(none) -> final response
        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(["{}", "Mocked response from env"])

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

        # Set mock responses for tool call then final response BEFORE creating ModelAPI
        # JSON action format: action(tool) -> action(none) -> final response
        mock_responses = [
            '{"tool": "calculator", "arguments": {"a": 5, "b": 3}}',
            "{}",
            "The result is 8.",
        ]
        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(mock_responses)

        try:
            # Use real ModelAPI - it reads env var in __init__
            model_api = ModelAPI(model="test", api_base="http://localhost:9999")

            agent = Agent(
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
        # Workflow: tool call -> delegation -> no-action -> final response (JSON action format)
        responses = [
            '{"tool": "fetch", "arguments": {"url": "http://example.com"}}',
            '{"agent": "analyzer", "task": "Analyze the data"}',
            "{}",  # No action - proceed to final response
            "Based on my analysis, the result is complete.",
        ]

        mock_model = MockModelAPI(responses=responses)
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

        agent = Agent(
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


class TestNativeToolCalling:
    """Tests for native tool calling path (function_calling='native')."""

    @pytest.mark.asyncio
    async def test_native_tool_dispatch(self):
        """Test that native mode dispatches tool_calls from ModelResponse to MCP tools."""
        mock_responses = [
            # First call: model returns tool call
            ModelResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="get_weather",
                        arguments='{"city": "London"}',
                    )
                ],
            ),
            # Second call: model returns final answer after seeing tool result
            ModelResponse(content="The weather in London is sunny."),
        ]

        mock_model = MockModelAPI(responses=mock_responses)
        mock_mcp = MockMCPClient(
            tools={"get_weather": ("Get weather for a city", {"weather": "sunny"})}
        )
        memory = LocalMemory()

        agent = Agent(
            name="native-tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
            function_calling="native",
        )

        result = []
        async for chunk in agent.process_message("What is the weather in London?"):
            result.append(chunk)

        response = "".join(result)

        # Verify tool was called
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "get_weather"
        assert mock_mcp.call_log[0]["args"] == {"city": "London"}

        # Verify final response contains expected content
        assert "sunny" in response.lower()

        # Verify memory events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert "agent_response" in event_types

        logger.info("✓ Native tool dispatch works")

    @pytest.mark.asyncio
    async def test_native_delegation_via_pseudo_tool(self):
        """Test that delegate_to_<name> tool calls trigger sub-agent delegation."""
        mock_responses = [
            # Model returns delegation pseudo-tool call
            ModelResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="delegate_to_coder",
                        arguments='{"task": "write hello world"}',
                    )
                ],
            ),
            # Model returns final answer after delegation
            ModelResponse(content="Delegation complete."),
        ]

        mock_model = MockModelAPI(responses=mock_responses)
        memory = LocalMemory()

        # Create mock remote sub-agent
        mock_remote = RemoteAgent(name="coder", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "coder",
                "description": "Coder agent",
                "url": "http://localhost:9999",
                "capabilities": ["task_execution"],
            },
        )()
        mock_remote._active = True
        mock_remote.process_message = AsyncMock(return_value="Code written")  # type: ignore[method-assign]

        agent = Agent(
            name="coordinator",
            model_api=mock_model,
            sub_agents=[mock_remote],
            memory=memory,
            max_steps=5,
            function_calling="native",
        )

        result = []
        async for chunk in agent.process_message("Write hello world"):
            result.append(chunk)

        # Verify delegation occurred
        mock_remote.process_message.assert_called_once()  # type: ignore[union-attr]
        call_args = mock_remote.process_message.call_args[0][0]  # type: ignore[union-attr]
        assert isinstance(call_args, list)
        assert call_args[-1]["role"] == "task-delegation"
        assert "write hello world" in call_args[-1]["content"]

        # Verify memory events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]
        assert "delegation_request" in event_types
        assert "delegation_response" in event_types

        logger.info("✓ Native delegation via pseudo-tool works")

    @pytest.mark.asyncio
    async def test_native_error_on_empty_response(self):
        """Test that native mode raises ValueError when model returns no tool_calls and no content."""
        mock_responses = [
            # Model returns empty response (no tool_calls, no content)
            ModelResponse(content=None, tool_calls=None),
        ]

        mock_model = MockModelAPI(responses=mock_responses)
        mock_mcp = MockMCPClient(tools={"get_weather": ("Get weather", {"weather": "sunny"})})
        memory = LocalMemory()

        agent = Agent(
            name="error-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
            function_calling="native",
        )

        result = []
        async for chunk in agent.process_message("What is the weather?"):
            result.append(chunk)

        response = "".join(result)
        # Agent catches ValueError and returns error message
        assert "error" in response.lower()

        logger.info("✓ Native error on empty response works")

    @pytest.mark.asyncio
    async def test_native_content_without_tool_calls_is_final_answer(self):
        """Test that native mode treats content-only response as final answer."""
        mock_responses = [
            # Model returns content without tool_calls — treated as direct answer
            ModelResponse(content="I can answer without tools: 42"),
        ]

        mock_model = MockModelAPI(responses=mock_responses)
        mock_mcp = MockMCPClient(tools={"calculator": ("Calculate things", {"result": 42})})
        memory = LocalMemory()

        agent = Agent(
            name="direct-answer-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
            function_calling="native",
        )

        result = []
        async for chunk in agent.process_message("What is the answer?"):
            result.append(chunk)

        response = "".join(result)
        # Model call count: 1 (action phase) + 1 (final phase) = 2
        assert mock_model.call_count == 2
        # No tools should have been called
        assert len(mock_mcp.call_log) == 0

        logger.info("✓ Native content without tool_calls is final answer")

    @pytest.mark.asyncio
    async def test_text_mode_unchanged(self):
        """Test that text mode uses _parse_action and does NOT send tools parameter."""
        mock_responses = [
            # Text mode: JSON action format for tool calling
            ModelResponse(content='{"tool": "get_weather", "arguments": {"city": "London"}}'),
            ModelResponse(content="{}"),  # No action - proceed to final
            ModelResponse(content="The weather is sunny."),
        ]

        mock_model = MockModelAPI(responses=mock_responses)
        mock_mcp = MockMCPClient(
            tools={"get_weather": ("Get weather for a city", {"weather": "sunny"})}
        )
        memory = LocalMemory()

        agent = Agent(
            name="text-mode-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=5,
            function_calling="text",  # Explicitly text mode
        )

        result = []
        async for chunk in agent.process_message("What is the weather?"):
            result.append(chunk)

        # Verify tools param was NOT sent (text mode)
        assert mock_model.last_tools is None

        # Verify tool was still dispatched via text parsing
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "get_weather"

        logger.info("✓ Text mode unchanged (no tools param, text parsing works)")

    @pytest.mark.asyncio
    async def test_native_tools_parameter_sent(self):
        """Test that native mode passes tools to process_message via _get_tools_for_api."""
        mock_responses = [
            # Model returns content (direct answer) — just need to verify tools were sent
            ModelResponse(content="Here is your answer."),
        ]

        mock_model = MockModelAPI(responses=mock_responses)
        mock_mcp = MockMCPClient(
            tools={
                "search": ("Search for info", {"results": []}),
                "calculate": ("Do math", {"result": 42}),
            }
        )
        memory = LocalMemory()

        # Create a sub-agent to check pseudo-tool registration
        mock_remote = RemoteAgent(name="helper", card_url="http://localhost:9999")
        mock_remote.agent_card = type(  # type: ignore[assignment]
            "AgentCard",
            (),
            {
                "name": "helper",
                "description": "Helper agent",
                "url": "http://localhost:9999",
                "capabilities": [],
            },
        )()
        mock_remote._active = True

        agent = Agent(
            name="tools-param-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            sub_agents=[mock_remote],
            memory=memory,
            max_steps=5,
            function_calling="native",
        )

        result = []
        async for chunk in agent.process_message("Test tools parameter"):
            result.append(chunk)

        # Verify tools were sent to process_message in Phase 1 (action collection)
        # Phase 2 (final response) does not send tools, so check the first call
        assert len(mock_model.all_tools_calls) >= 1
        phase1_tools = mock_model.all_tools_calls[0]
        assert phase1_tools is not None
        assert len(phase1_tools) == 3  # 2 MCP tools + 1 pseudo-tool

        # Verify OpenAI format
        for tool in phase1_tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]

        # Verify pseudo-tool for sub-agent
        delegate_tools = [
            t for t in phase1_tools if t["function"]["name"].startswith("delegate_to_")
        ]
        assert len(delegate_tools) == 1
        assert delegate_tools[0]["function"]["name"] == "delegate_to_helper"

        # Verify Phase 2 does NOT send tools
        assert mock_model.all_tools_calls[-1] is None

        logger.info("✓ Native tools parameter sent correctly")


class TestParseActionEdgeCases:
    """Tests for _parse_action edge cases: nested JSON, escaped quotes, multiple objects."""

    def _make_agent(self):
        """Create an agent instance for testing _parse_action."""
        mock_model = MockModelAPI(["test"])
        return Agent(name="parser-test", model_api=mock_model)

    def test_nested_json_in_tool_arguments(self):
        """Test parsing tool call with nested JSON objects in arguments."""
        agent = self._make_agent()
        content = '{"tool": "write_file", "arguments": {"path": "config.json", "content": "{\\"key\\": \\"value\\"}"}}'
        result = agent._parse_action(content)
        assert result["tool"] == "write_file"
        assert result["arguments"]["path"] == "config.json"

    def test_escaped_quotes_in_string_values(self):
        """Test parsing JSON with escaped quotes inside string values."""
        agent = self._make_agent()
        content = '{"tool": "echo", "arguments": {"text": "He said \\"hello\\""}}'
        result = agent._parse_action(content)
        assert result["tool"] == "echo"
        assert "hello" in result["arguments"]["text"]

    def test_multiple_json_objects_returns_first_action(self):
        """Test that multiple JSON objects returns the first valid action."""
        agent = self._make_agent()
        content = """I'll do two things:
```json
{"tool": "read_file", "arguments": {"path": "a.txt"}}
```
Then:
```json
{"tool": "read_file", "arguments": {"path": "b.txt"}}
```"""
        result = agent._parse_action(content)
        assert result["tool"] == "read_file"
        assert result["arguments"]["path"] == "a.txt"

    def test_json_in_code_fences(self):
        """Test parsing JSON wrapped in code fences."""
        agent = self._make_agent()
        content = """Here is the action:
```json
{"tool": "search", "arguments": {"query": "test"}}
```
That's the search."""
        result = agent._parse_action(content)
        assert result["tool"] == "search"
        assert result["arguments"]["query"] == "test"

    def test_pretty_printed_json(self):
        """Test parsing pretty-printed JSON with whitespace and newlines."""
        agent = self._make_agent()
        content = """{
    "tool": "calculator",
    "arguments": {
        "a": 5,
        "b": 3
    }
}"""
        result = agent._parse_action(content)
        assert result["tool"] == "calculator"
        assert result["arguments"]["a"] == 5

    def test_deeply_nested_json(self):
        """Test parsing deeply nested JSON structures."""
        agent = self._make_agent()
        content = '{"tool": "api_call", "arguments": {"body": {"data": {"items": [{"id": 1}]}}}}'
        result = agent._parse_action(content)
        assert result["tool"] == "api_call"
        assert result["arguments"]["body"]["data"]["items"][0]["id"] == 1

    def test_braces_inside_strings_ignored(self):
        """Test that braces inside string values don't break brace matching."""
        agent = self._make_agent()
        content = '{"tool": "echo", "arguments": {"text": "use {curly} braces {here}"}}'
        result = agent._parse_action(content)
        assert result["tool"] == "echo"
        assert "{curly}" in result["arguments"]["text"]

    def test_no_valid_action_returns_empty(self):
        """Test that content without valid action JSON returns empty dict."""
        agent = self._make_agent()
        result = agent._parse_action("Just a plain text response with no JSON.")
        assert result == {}

    def test_empty_action_detected(self):
        """Test that empty JSON object is detected as no-action signal."""
        agent = self._make_agent()
        result = agent._parse_action("I'm done now. {}")
        assert result == {}

    def test_extract_json_objects_returns_all(self):
        """Test that _extract_json_objects extracts all JSON objects from text."""
        agent = self._make_agent()
        content = 'First: {"a": 1} then {"b": 2} and {"c": 3}'
        results = agent._extract_json_objects(content)
        assert len(results) == 3
        assert results[0] == {"a": 1}
        assert results[1] == {"b": 2}
        assert results[2] == {"c": 3}

    def test_backslash_in_json_string(self):
        """Test parsing JSON with backslashes in string values."""
        agent = self._make_agent()
        content = '{"tool": "write", "arguments": {"path": "C:\\\\Users\\\\file.txt"}}'
        result = agent._parse_action(content)
        assert result["tool"] == "write"
        assert "Users" in result["arguments"]["path"]
