"""
KAOS tool utilities — delegation toolset and string-mode model handler.

Provides:
- DelegationToolset: Pydantic AI AbstractToolset for sub-agent delegation
- execute_delegation: HTTP delegation to remote agents
- format_progress_event: SSE progress event formatting
- String-mode tool calling (build_string_mode_handler, parse_tool_calls_from_text)
"""

import json
import logging
import re
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

import httpx
from pydantic_ai.toolsets.abstract import AbstractToolset, ToolsetTool
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
    SystemPromptPart,
)
from pydantic_ai import RunContext
from pydantic_core import SchemaValidator, core_schema

from pai_server.telemetry import (
    SERVICE_NAME,
    get_delegation_metrics,
    ATTR_DELEGATION_TARGET,
)
from opentelemetry import trace as trace_api

if TYPE_CHECKING:
    from pai_server.serverutils import AgentDeps, RemoteAgent
    from pai_server.memory import Memory

logger = logging.getLogger(__name__)

DELEGATION_TOOL_PREFIX = "delegate_to_"

_TASK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"task": {"type": "string", "description": "Task to delegate to the agent"}},
    "required": ["task"],
}
_VALIDATOR = SchemaValidator(schema=core_schema.any_schema())


class DelegationToolset(AbstractToolset["AgentDeps"]):
    """Pydantic AI toolset that exposes sub-agents as delegate_to_{name} tools."""

    def __init__(
        self,
        sub_agents: Dict[str, "RemoteAgent"],
        memory_context_limit: int = 6,
    ):
        self._sub_agents = sub_agents
        self._memory_context_limit = memory_context_limit

    @property
    def id(self) -> str:
        return "kaos-delegation"

    async def get_tools(self, ctx: RunContext["AgentDeps"]) -> dict[str, ToolsetTool["AgentDeps"]]:
        tools: dict[str, ToolsetTool["AgentDeps"]] = {}
        for name, remote in self._sub_agents.items():
            # Always expose tools — RemoteAgent lazy-inits on first call
            desc = f"Delegate a task to the {name} agent."
            if remote.agent_card:
                desc = (
                    f"Delegate a task to the {remote.agent_card.name} agent: "
                    f"{remote.agent_card.description}"
                )
            tool_name = f"{DELEGATION_TOOL_PREFIX}{name}"
            tools[tool_name] = ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=tool_name,
                    description=desc,
                    parameters_json_schema=_TASK_SCHEMA,
                ),
                max_retries=0,
                args_validator=_VALIDATOR,
            )
        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext["AgentDeps"],
        tool: ToolsetTool["AgentDeps"],
    ) -> str:
        agent_name = name.removeprefix(DELEGATION_TOOL_PREFIX)
        return await execute_delegation(
            agent_name,
            tool_args["task"],
            self._sub_agents[agent_name],
            ctx.deps.session_id,
            ctx.deps.memory,
            self._memory_context_limit,
        )


async def execute_delegation(
    agent_name: str,
    task: str,
    sub_agent: "RemoteAgent",
    session_id: str = "",
    memory: Optional["Memory"] = None,
    memory_context_limit: int = 6,
) -> str:
    """Execute delegation to a sub-agent, forwarding conversation context."""
    tracer = trace_api.get_tracer(SERVICE_NAME)
    delegation_counter, delegation_duration = get_delegation_metrics()
    start_time = time.perf_counter()
    success = False

    with tracer.start_as_current_span(
        f"delegate.{agent_name}",
        attributes={ATTR_DELEGATION_TARGET: agent_name},
    ) as span:
        try:
            messages: List[Dict[str, str]] = []

            if session_id and memory:
                events = await memory.get_session_events(session_id)
                context_events = events[-memory_context_limit:] if events else []
                for event in context_events:
                    if event.event_type in ("user_message", "task_delegation_received"):
                        messages.append({"role": "user", "content": str(event.content)})
                    elif event.event_type == "agent_response":
                        messages.append({"role": "assistant", "content": str(event.content)})

            messages.append({"role": "task-delegation", "content": task})
            result = await sub_agent.process_message(messages)
            success = True
            return result
        except Exception as e:
            logger.error(f"Delegation to {agent_name} failed: {type(e).__name__}: {e}")
            from opentelemetry.trace import StatusCode, Status

            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            return f"[Delegation failed: {e}]"
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            if delegation_counter and delegation_duration:
                labels = {"target": agent_name, "success": str(success).lower()}
                delegation_counter.add(1, labels)
                delegation_duration.record(duration_ms, labels)


def format_progress_event(part: ToolCallPart, step: int, max_steps: int) -> str:
    """Format a tool call as a JSON progress event for streaming."""
    is_deleg = part.tool_name.startswith(DELEGATION_TOOL_PREFIX)
    return json.dumps(
        {
            "type": "progress",
            "step": step,
            "max_steps": max_steps,
            "action": "delegate" if is_deleg else "tool_call",
            "target": (
                part.tool_name[len(DELEGATION_TOOL_PREFIX) :] if is_deleg else part.tool_name
            ),
        }
    )


# --- String-mode tool calling ---

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

    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
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

    if "tool_calls" in parsed:
        calls = parsed["tool_calls"]
        if isinstance(calls, list) and len(calls) > 0:
            return calls
        return None

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
        oai_messages: List[Dict[str, str]] = []

        tools = list(info.function_tools) + list(info.output_tools)
        if tools:
            tool_desc = build_tool_descriptions(tools)
            tool_prompt = TOOL_PROMPT_TEMPLATE.format(tool_descriptions=tool_desc)

            if info.instructions:
                oai_messages.append(
                    {"role": "system", "content": info.instructions + "\n\n" + tool_prompt}
                )
            else:
                oai_messages.append({"role": "system", "content": tool_prompt})
        elif info.instructions:
            oai_messages.append({"role": "system", "content": info.instructions})

        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        oai_messages.append({"role": "user", "content": str(part.content)})
                    elif isinstance(part, SystemPromptPart):
                        pass
                    elif isinstance(part, TextPart):
                        oai_messages.append({"role": "assistant", "content": part.content})
                    elif isinstance(part, ToolCallPart):
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
                        oai_messages.append(
                            {"role": "user", "content": f"Tool result: {part.content}"}
                        )

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
