"""Tests for string-mode tool calling."""

import json
import os
import pytest

from agent.tools import (
    build_tool_descriptions,
    parse_tool_calls_from_text,
    build_string_mode_handler,
)
from pydantic_ai.models import ToolDefinition

# ────────────────────────────────────────────────────────────────────────────
# Tool Description Tests
# ────────────────────────────────────────────────────────────────────────────


class TestBuildToolDescriptions:
    """Tests for tool description formatting."""

    def test_single_tool(self):
        tool = ToolDefinition(
            name="echo",
            description="Echo a message",
            parameters_json_schema={
                "type": "object",
                "properties": {"message": {"type": "string", "description": "The message"}},
                "required": ["message"],
            },
        )
        result = build_tool_descriptions([tool])
        assert "echo" in result
        assert "Echo a message" in result
        assert "message" in result
        assert "(required)" in result

    def test_multiple_tools(self):
        tools = [
            ToolDefinition(
                name="add",
                description="Add numbers",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            ),
            ToolDefinition(
                name="echo",
                description="Echo text",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
        ]
        result = build_tool_descriptions(tools)
        assert "add" in result
        assert "echo" in result

    def test_tool_no_description(self):
        tool = ToolDefinition(
            name="noop",
            description="",
            parameters_json_schema={"type": "object", "properties": {}},
        )
        result = build_tool_descriptions([tool])
        assert "noop" in result
        assert "No description" in result

    def test_delegation_tool(self):
        tool = ToolDefinition(
            name="delegate_to_worker",
            description="Delegate to worker agent",
            parameters_json_schema={
                "type": "object",
                "properties": {"task": {"type": "string", "description": "Task"}},
                "required": ["task"],
            },
        )
        result = build_tool_descriptions([tool])
        assert "delegate_to_worker" in result

    def test_empty_tools(self):
        result = build_tool_descriptions([])
        assert result == ""


# ────────────────────────────────────────────────────────────────────────────
# Tool Call Parsing Tests
# ────────────────────────────────────────────────────────────────────────────


class TestParseToolCallsFromText:
    """Tests for parsing tool calls from model response text."""

    def test_single_tool_call(self):
        text = '{"tool_calls": [{"name": "echo", "arguments": {"message": "hello"}}]}'
        result = parse_tool_calls_from_text(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "echo"
        assert result[0]["arguments"]["message"] == "hello"

    def test_multiple_tool_calls(self):
        text = json.dumps(
            {
                "tool_calls": [
                    {"name": "add", "arguments": {"a": 1, "b": 2}},
                    {"name": "echo", "arguments": {"text": "hi"}},
                ]
            }
        )
        result = parse_tool_calls_from_text(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "add"
        assert result[1]["name"] == "echo"

    def test_single_tool_shorthand(self):
        text = '{"name": "echo", "arguments": {"message": "hi"}}'
        result = parse_tool_calls_from_text(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "echo"

    def test_delegation_tool_call(self):
        text = '{"tool_calls": [{"name": "delegate_to_worker", "arguments": {"task": "process"}}]}'
        result = parse_tool_calls_from_text(text)
        assert result is not None
        assert result[0]["name"] == "delegate_to_worker"

    def test_plain_text_returns_none(self):
        result = parse_tool_calls_from_text("This is just a normal response.")
        assert result is None

    def test_empty_text_returns_none(self):
        assert parse_tool_calls_from_text("") is None
        assert parse_tool_calls_from_text("   ") is None
        assert parse_tool_calls_from_text(None) is None

    def test_malformed_json_returns_none(self):
        result = parse_tool_calls_from_text('{"tool_calls": [{"name": "broken"')
        assert result is None

    def test_json_in_markdown_fence(self):
        text = '```json\n{"tool_calls": [{"name": "echo", "arguments": {"msg": "hi"}}]}\n```'
        result = parse_tool_calls_from_text(text)
        assert result is not None
        assert result[0]["name"] == "echo"

    def test_json_with_surrounding_text(self):
        text = 'I will call the tool now:\n{"tool_calls": [{"name": "echo", "arguments": {"msg": "hi"}}]}\nDone.'
        result = parse_tool_calls_from_text(text)
        assert result is not None
        assert result[0]["name"] == "echo"

    def test_empty_tool_calls_returns_none(self):
        text = '{"tool_calls": []}'
        result = parse_tool_calls_from_text(text)
        assert result is None

    def test_irrelevant_json_returns_none(self):
        text = '{"status": "ok", "data": 42}'
        result = parse_tool_calls_from_text(text)
        assert result is None


# ────────────────────────────────────────────────────────────────────────────
# Agent Integration Tests
# ────────────────────────────────────────────────────────────────────────────


class TestStringModeAgentIntegration:
    """Tests for string-mode integration with Agent."""

    def test_agent_accepts_tool_call_mode(self):
        """Agent can be constructed with tool_call_mode parameter."""
        from agent.client import Agent

        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(["hello"])
        try:
            agent = Agent(
                name="test-agent",
                instructions="Test",
                tool_call_mode="string",
            )
            assert agent.tool_call_mode == "string"
        finally:
            del os.environ["DEBUG_MOCK_RESPONSES"]

    def test_agent_default_tool_call_mode(self):
        """Agent defaults to 'auto' tool_call_mode."""
        from agent.client import Agent

        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(["hello"])
        try:
            agent = Agent(name="test-agent", instructions="Test")
            assert agent.tool_call_mode == "auto"
        finally:
            del os.environ["DEBUG_MOCK_RESPONSES"]

    def test_agent_string_mode_with_model_url(self):
        """Agent with string mode and model URL uses FunctionModel."""
        from agent.client import Agent
        from pydantic_ai.models.function import FunctionModel

        agent = Agent(
            name="test-agent",
            instructions="Test",
            model_api_url="http://localhost:11434",
            model_name="test-model",
            tool_call_mode="string",
        )
        assert isinstance(agent._model, FunctionModel)

    def test_agent_native_mode_with_model_url(self):
        """Agent with native mode and model URL uses OpenAIChatModel."""
        from agent.client import Agent
        from pydantic_ai.models.openai import OpenAIChatModel

        agent = Agent(
            name="test-agent",
            instructions="Test",
            model_api_url="http://localhost:11434",
            model_name="test-model",
            tool_call_mode="native",
        )
        assert isinstance(agent._model, OpenAIChatModel)

    @pytest.mark.asyncio
    async def test_string_mode_agent_with_mock_responses(self):
        """String-mode agent works with mock responses (mock takes priority over string mode)."""
        from agent.client import Agent

        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(["Mock response"])
        try:
            agent = Agent(
                name="test-agent",
                instructions="Test",
                tool_call_mode="string",
            )
            chunks = []
            async for chunk in agent.process_message("hello"):
                chunks.append(chunk)
            assert "Mock response" in "".join(chunks)
        finally:
            del os.environ["DEBUG_MOCK_RESPONSES"]


# ────────────────────────────────────────────────────────────────────────────
# Server Settings Tests
# ────────────────────────────────────────────────────────────────────────────


class TestServerSettingsToolCallMode:
    """Tests for tool_call_mode in AgentServerSettings."""

    def test_default_tool_call_mode(self):
        from agent.server import AgentServerSettings

        settings = AgentServerSettings(agent_name="test", model_api_url="http://x", model_name="m")
        assert settings.tool_call_mode == "auto"

    def test_string_tool_call_mode(self):
        from agent.server import AgentServerSettings

        os.environ["TOOL_CALL_MODE"] = "string"
        try:
            settings = AgentServerSettings(
                agent_name="test", model_api_url="http://x", model_name="m"
            )
            assert settings.tool_call_mode == "string"
        finally:
            del os.environ["TOOL_CALL_MODE"]
