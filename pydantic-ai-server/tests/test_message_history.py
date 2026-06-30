"""Tests for the message-history bridge.

Cover the two pure helpers the runtime uses to round-trip working-tier turns
through Pydantic AI ``message_history``: capturing all replay-relevant message
parts as faithful turns, and reconstructing history with rolling-summary overflow
instead of truncation.
"""

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from pais.memory import pydantic_message_to_turns, reconstruct_message_history


class TestPydanticMessageToTurns:
    def test_captures_user_prompt(self):
        msg = ModelRequest(parts=[UserPromptPart(content="hello")])
        assert pydantic_message_to_turns(msg) == [("user", "hello")]

    def test_captures_assistant_text(self):
        msg = ModelResponse(parts=[TextPart(content="hi there")])
        assert pydantic_message_to_turns(msg) == [("assistant", "hi there")]

    def test_captures_tool_call_as_faithful_text(self):
        msg = ModelResponse(parts=[ToolCallPart(tool_name="calculator", args={"a": 1, "b": 2})])
        turns = pydantic_message_to_turns(msg)
        assert len(turns) == 1
        role, content = turns[0]
        assert role == "assistant"
        assert "called tool calculator" in content
        assert '"a": 1' in content

    def test_captures_tool_return(self):
        msg = ModelRequest(parts=[ToolReturnPart(tool_name="calculator", content={"result": 3})])
        turns = pydantic_message_to_turns(msg)
        assert turns[0][0] == "tool"
        assert "tool result calculator" in turns[0][1]
        assert "result" in turns[0][1]

    def test_captures_delegation_request_and_response(self):
        call = ModelResponse(
            parts=[ToolCallPart(tool_name="delegate_to_researcher", args={"task": "x"})]
        )
        ret = ModelRequest(
            parts=[ToolReturnPart(tool_name="delegate_to_researcher", content="done")]
        )
        assert "delegated to delegate_to_researcher" in pydantic_message_to_turns(call)[0][1]
        assert "delegation result delegate_to_researcher" in pydantic_message_to_turns(ret)[0][1]

    def test_empty_text_is_skipped(self):
        msg = ModelResponse(parts=[TextPart(content="")])
        assert pydantic_message_to_turns(msg) == []


class TestReconstructMessageHistory:
    def test_returns_none_when_empty(self):
        assert reconstruct_message_history([], "") is None

    def test_rebuilds_user_and_assistant_turns(self):
        history = reconstruct_message_history([("user", "hi"), ("assistant", "hello")])
        assert history is not None
        assert isinstance(history[0], ModelRequest)
        assert isinstance(history[1], ModelResponse)
        assert history[0].parts[0].content == "hi"
        assert history[1].parts[0].content == "hello"

    def test_summary_is_prepended_as_context_not_truncated(self):
        history = reconstruct_message_history(
            [("user", "latest")], summary="earlier we discussed tea"
        )
        assert history is not None
        # First entry carries the summary, so older context survives as summary.
        assert "earlier we discussed tea" in history[0].parts[0].content
        assert history[-1].parts[0].content == "latest"

    def test_context_limit_keeps_most_recent_turns(self):
        turns = [("user", f"m{i}") for i in range(10)]
        history = reconstruct_message_history(turns, context_limit=3)
        assert history is not None
        assert len(history) == 3
        assert history[-1].parts[0].content == "m9"
        assert history[0].parts[0].content == "m7"

    def test_summary_survives_context_limit(self):
        turns = [("user", f"m{i}") for i in range(10)]
        history = reconstruct_message_history(turns, summary="older stuff", context_limit=2)
        assert history is not None
        # summary entry + 2 most-recent turns
        assert len(history) == 3
        assert "older stuff" in history[0].parts[0].content
        assert history[-1].parts[0].content == "m9"

    def test_tool_turns_replay_as_assistant_text(self):
        history = reconstruct_message_history([("tool", "[tool result x: 3]")])
        assert history is not None
        assert isinstance(history[0], ModelResponse)
        assert history[0].parts[0].content == "[tool result x: 3]"
