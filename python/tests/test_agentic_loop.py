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
from modelapi.client import ModelAPI
from mcptools.client import MCPClient, Tool

logger = logging.getLogger(__name__)


class MockModelAPI(ModelAPI):
    """Mock ModelAPI that returns predetermined responses."""

    def __init__(self, responses: Optional[list] = None):
        """Initialize with a list of responses to return in sequence."""
        self.responses = list(responses) if responses else ["Default mock response"]
        self.call_count = 0
        self.model = "mock"
        self.api_base = "mock://localhost"
        self.client = None  # Not used
        self._mock_responses: Optional[List[str]] = None  # Not used in mock

    async def process_message(self, messages, stream=False):
        """Return next response from the list.

        Returns str if stream=False, AsyncIterator[str] if stream=True.
        """
        content = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        if stream:
            return self._yield_content(content)
        return content

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
        # Mock response that includes a tool call
        tool_call_response = """I'll calculate that for you.
```tool_call
{"tool": "calculator", "arguments": {"a": 5, "b": 3}}
```"""
        final_response = "The result is 8."

        mock_model = MockModelAPI(responses=[tool_call_response, final_response])
        mock_mcp = MockMCPClient(tools={"calculator": ("Add two numbers", {"sum": 8})})
        memory = LocalMemory()

        agent = Agent(
            name="tool-agent",
            model_api=mock_model,
            mcp_clients=[mock_mcp],
            memory=memory,
            max_steps=3,
        )

        # Process message
        result = []
        async for chunk in agent.process_message("What is 5 + 3?"):
            result.append(chunk)

        response = "".join(result)

        # Verify tool was called
        assert len(mock_mcp.call_log) == 1
        assert mock_mcp.call_log[0]["tool"] == "calculator"

        # Verify model was called twice (tool call + final response)
        assert mock_model.call_count == 2

        # Verify memory has tool events
        sessions = await memory.list_sessions()
        events = await memory.get_session_events(sessions[0])
        event_types = [e.event_type for e in events]

        assert "user_message" in event_types
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert "agent_response" in event_types

        logger.info("✓ Tool call detection and execution works")


class TestAgenticLoopDelegation:
    """Tests for agent delegation in the agentic loop."""

    @pytest.mark.asyncio
    async def test_delegation_detected_and_executed(self):
        """Test that a delegation in model response triggers sub-agent invocation."""
        delegation_response = """I'll delegate this to the worker.
```delegate
{"agent": "worker", "task": "Process this data"}
```"""
        final_response = "The worker processed the data successfully."

        mock_model = MockModelAPI(responses=[delegation_response, final_response])
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
            max_steps=3,
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

        # Verify model was called twice
        assert mock_model.call_count == 2

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
        # Model always returns a tool call
        infinite_tool_call = """```tool_call
{"tool": "loop_tool", "arguments": {}}
```"""

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
        # Create mock model that returns delegation then final response
        delegation_response = """I'll delegate this.
```delegate
{"agent": "worker", "task": "Do the work"}
```"""
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
        assert "tool_call" in prompt

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

        # Verify the model was called (we can't easily check the exact prompt
        # without more intrusive mocking, but we verify the flow completes)
        assert len(result) > 0
        assert mock_model.call_count == 1

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

        # Set mock responses for tool call then final response BEFORE creating ModelAPI
        mock_responses = [
            """```tool_call
{"tool": "calculator", "arguments": {"a": 5, "b": 3}}
```""",
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

            # Should get final response after tool call
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
        responses = [
            """```tool_call
{"tool": "fetch", "arguments": {"url": "http://example.com"}}
```""",
            """```delegate
{"agent": "analyzer", "task": "Analyze the data"}
```""",
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
