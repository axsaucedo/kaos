"""
String-mode tool calling for models without native function calling support.

Wraps an OpenAI-compatible model to inject tool descriptions into the system
prompt and parse tool call JSON from the response text. This enables tool
calling with models that don't support the OpenAI tools API.

Used when TOOL_CALL_MODE=string.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

import httpx
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
    SystemPromptPart,
)
from pydantic_ai.models import ToolDefinition

logger = logging.getLogger(__name__)

TOOL_PROMPT_TEMPLATE = """
You have access to the following tools. To use a tool, respond ONLY with a JSON object in this exact format:

{{"tool_calls": [{{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}]}}

Available tools:
{tool_descriptions}

IMPORTANT:
- When using a tool, your ENTIRE response must be the JSON object above, nothing else.
- You may call multiple tools at once by adding more items to the tool_calls array.
- When you have all the information you need, respond with plain text (no JSON).
"""


def build_tool_descriptions(tools: List[ToolDefinition]) -> str:
    """Format tool definitions as text descriptions for the system prompt."""
    descriptions = []
    for tool in tools:
        params = tool.parameters_json_schema
        props = params.get("properties", {})
        required = params.get("required", [])

        param_lines = []
        for pname, pschema in props.items():
            req = " (required)" if pname in required else ""
            ptype = pschema.get("type", "any")
            pdesc = pschema.get("description", "")
            param_lines.append(
                f"    - {pname}: {ptype}{req} — {pdesc}"
                if pdesc
                else f"    - {pname}: {ptype}{req}"
            )

        desc = tool.description or "No description"
        tool_text = f"- {tool.name}: {desc}"
        if param_lines:
            tool_text += "\n  Parameters:\n" + "\n".join(param_lines)
        descriptions.append(tool_text)

    return "\n".join(descriptions)


def parse_tool_calls_from_text(
    text: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """Parse tool call JSON from model response text.

    Supports:
    - {"tool_calls": [{"name": "...", "arguments": {...}}]}
    - {"name": "...", "arguments": {...}} (single tool)

    Returns list of tool call dicts, or None if no tool calls found.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Try to extract JSON from the text (may have markdown fencing)
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # Try parsing as JSON
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                parsed = json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(parsed, dict):
        return None

    # Format: {"tool_calls": [...]}
    if "tool_calls" in parsed:
        calls = parsed["tool_calls"]
        if isinstance(calls, list) and len(calls) > 0:
            return calls
        return None

    # Format: {"name": "...", "arguments": {...}}
    if "name" in parsed and "arguments" in parsed:
        return [parsed]

    return None


def build_string_mode_handler(base_url: str, model_name: str, api_key: str = "not-needed"):
    """Build a FunctionModel handler that uses string-mode tool calling.

    Args:
        base_url: OpenAI-compatible API base URL (should include /v1)
        model_name: Model name for the API
        api_key: API key (default: "not-needed" for local models)

    Returns:
        Async FunctionModel handler function
    """

    async def string_mode_handler(messages: list[ModelRequest], info: AgentInfo) -> ModelResponse:
        """Handle model calls with string-mode tool calling."""
        # Build OpenAI-format messages
        oai_messages: List[Dict[str, str]] = []

        # Add system prompt with tool descriptions if tools available
        tools = list(info.function_tools) + list(info.output_tools)
        if tools:
            tool_desc = build_tool_descriptions(tools)
            tool_prompt = TOOL_PROMPT_TEMPLATE.format(tool_descriptions=tool_desc)

            # Prepend tool instructions to system prompt
            if info.instructions:
                oai_messages.append(
                    {"role": "system", "content": info.instructions + "\n\n" + tool_prompt}
                )
            else:
                oai_messages.append({"role": "system", "content": tool_prompt})
        elif info.instructions:
            oai_messages.append({"role": "system", "content": info.instructions})

        # Convert Pydantic AI messages to OpenAI format
        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        oai_messages.append({"role": "user", "content": str(part.content)})
                    elif isinstance(part, SystemPromptPart):
                        # Already handled above
                        pass
                    elif isinstance(part, TextPart):
                        oai_messages.append({"role": "assistant", "content": part.content})
                    elif isinstance(part, ToolCallPart):
                        # Previous tool call — include as assistant message
                        call_json = json.dumps(
                            {
                                "tool_calls": [
                                    {
                                        "name": part.tool_name,
                                        "arguments": (
                                            part.args if isinstance(part.args, dict) else {}
                                        ),
                                    }
                                ]
                            }
                        )
                        oai_messages.append({"role": "assistant", "content": call_json})
                    elif hasattr(part, "content"):
                        # ToolReturnPart or similar — include as user message
                        oai_messages.append(
                            {"role": "user", "content": f"Tool result: {part.content}"}
                        )

        # Call the model via httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json={
                        "model": model_name,
                        "messages": oai_messages,
                        "stream": False,
                    },
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"] or ""
            except Exception as e:
                logger.error(f"String-mode model call failed: {type(e).__name__}: {e}")
                return ModelResponse(parts=[TextPart(content=f"[Model error: {e}]")])

        # Try to parse tool calls from the response text
        if tools:
            tool_calls = parse_tool_calls_from_text(content)
            if tool_calls:
                parts = []
                for tc in tool_calls:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("arguments", {})
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}
                    parts.append(
                        ToolCallPart(
                            tool_name=tool_name,
                            args=tool_args,
                            tool_call_id=f"string_{tool_name}",
                        )
                    )
                if parts:
                    return ModelResponse(parts=parts)

        return ModelResponse(parts=[TextPart(content=content)])

    return string_mode_handler
