"""
Agent client implementation for OpenAI-compatible API.

Clean, simple implementation with proper streaming support and tool integration.
Auto-detects native tool calling support via litellm model registry:
- Models with native support: uses OpenAI tools API for structured function calling
- Models without native support: uses text-based JSON parsing from model content
Instrumented with OpenTelemetry for tracing and metrics.

Key design principles:
- Auto-detection of native tool calling support (no manual configuration)
- Sub-agent delegation exposed as delegate_to_{name} tool functions (both modes)
- Server only routes requests, never interprets delegation
- DEBUG_MOCK_RESPONSES env var handled by ModelAPI for testing
- RemoteAgent.process_message() uses /v1/chat/completions
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, AsyncIterator, Union, cast
from dataclasses import dataclass

import litellm
import httpx
from modelapi.client import ModelAPI, ModelResponse, ToolCall
from agent.memory import LocalMemory, NullMemory
from mcptools.client import MCPClient
from telemetry.manager import (
    otel,
    KaosOtelManager,
    ATTR_SESSION_ID,
    ATTR_MODEL_NAME,
    ATTR_TOOL_NAME,
    ATTR_DELEGATION_TARGET,
)
from opentelemetry.trace import SpanKind

logger = logging.getLogger(__name__)

# Type alias for memory implementations
Memory = LocalMemory | NullMemory

DELEGATION_TOOL_PREFIX = "delegate_to_"

# System prompt template for string-mode tool calling
STRING_MODE_TOOLS_PROMPT = """
To use tools, respond with ONLY a JSON object in this format:
{"tool_calls": [{"name": "tool_name", "arguments": {"arg1": "value1"}}]}

You can call multiple tools at once:
{"tool_calls": [{"name": "tool1", "arguments": {...}}, {"name": "tool2", "arguments": {...}}]}

When you have all the information needed, respond WITHOUT any JSON tool call.
"""


@dataclass
class AgentCard:
    """Agent discovery card for A2A protocol."""

    name: str
    description: str
    url: str
    skills: List[Dict[str, Any]]
    capabilities: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "skills": self.skills,
            "capabilities": self.capabilities,
        }


class RemoteAgent:
    """Remote agent client for A2A protocol with graceful degradation.

    Uses /v1/chat/completions for invocation to pass full context.
    The role "task-delegation" indicates this is a delegated task.
    """

    DISCOVERY_TIMEOUT = 5.0  # Short timeout for agent card discovery
    REQUEST_TIMEOUT = 60.0  # Longer timeout for actual requests

    def __init__(
        self,
        name: str,
        card_url: Optional[str] = None,
        agent_card_url: Optional[str] = None,
    ):
        url = card_url or agent_card_url
        if not url:
            raise ValueError("card_url is required")
        self.name = name
        self.card_url = url.rstrip("/")
        self.agent_card: Optional[AgentCard] = None
        self._active = False
        self._discovery_client = httpx.AsyncClient(timeout=self.DISCOVERY_TIMEOUT)
        self._request_client = httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT)
        logger.info(f"RemoteAgent initialized: {name} -> {url}")

    async def _init(self) -> bool:
        """Fetch agent card and activate. Returns True if successful."""
        try:
            response = await self._discovery_client.get(f"{self.card_url}/.well-known/agent")
            response.raise_for_status()
            data = response.json()
            self.agent_card = AgentCard(
                name=data.get("name", self.name),
                description=data.get("description", ""),
                url=self.card_url,
                skills=data.get("skills", []),
                capabilities=data.get("capabilities", []),
            )
            self._active = True
            logger.info(f"RemoteAgent {self.name} active: {self.agent_card.description}")
            return True
        except Exception as e:
            self._active = False
            logger.warning(f"RemoteAgent {self.name} init failed: {type(e).__name__}: {e}")
            return False

    async def process_message(
        self,
        messages: List[Dict[str, str]],
    ) -> str:
        """Process messages via remote agent's /v1/chat/completions.

        Injects trace context headers for distributed tracing across agents.

        Args:
            messages: List of messages providing context. The last message
                     should have role "task-delegation" with the delegated task.

        Returns:
            The agent's response content.

        Raises:
            RuntimeError: If agent is unavailable or request fails.
        """
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")

        try:
            # Inject trace context for distributed tracing
            headers: Dict[str, str] = {}
            KaosOtelManager.inject_context(headers)

            response = await self._request_client.post(
                f"{self.card_url}/v1/chat/completions",
                json={"model": self.name, "messages": messages, "stream": False},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            self._active = False
            logger.error(f"RemoteAgent {self.name} request failed: {type(e).__name__}: {e}")
            raise RuntimeError(f"Agent {self.name}: {type(e).__name__}: {e}")

    async def close(self):
        """Close HTTP clients."""
        try:
            await self._discovery_client.aclose()
            await self._request_client.aclose()
        except Exception:
            pass


class Agent:
    """Agent class with agentic loop support for tool calling and delegation."""

    def __init__(
        self,
        name: str,
        model_api: ModelAPI,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: Optional[Memory] = None,
        mcp_clients: Optional[List[MCPClient]] = None,
        sub_agents: Optional[List[RemoteAgent]] = None,
        max_steps: int = 5,
        memory_context_limit: int = 6,
        memory_enabled: bool = True,
        tool_call_mode: str = "auto",
    ):
        self.name = name
        self.instructions = instructions
        self.model_api = model_api
        self.memory: Memory = memory or LocalMemory()
        self.description = description
        self.mcp_clients = mcp_clients or []
        self.sub_agents: Dict[str, RemoteAgent] = {
            agent.name: agent for agent in (sub_agents or [])
        }
        self.max_steps = max_steps
        self.memory_context_limit = memory_context_limit
        self.memory_enabled = memory_enabled

        # Determine native tool calling support based on mode
        self._supports_native_tools = self._check_native_tool_support(
            model_api.model, tool_call_mode
        )
        logger.info(
            f"Agent initialized: {name} (tool_call_mode={tool_call_mode}, "
            f"native_tools={self._supports_native_tools})"
        )

    @staticmethod
    def _check_native_tool_support(model: str, tool_call_mode: str = "auto") -> bool:
        """Determine native tool calling support based on mode.

        - "auto": auto-detect via litellm model registry
        - "native": force native tool calling
        - "string": force string-based tool calling
        """
        if tool_call_mode == "native":
            return True
        if tool_call_mode == "string":
            return False
        try:
            return litellm.supports_function_calling(model=model)
        except Exception:
            return False

    async def _build_tools_param(self) -> Optional[List[Dict[str, Any]]]:
        """Build OpenAI tools parameter from MCP tools and sub-agents.

        Returns:
            List of tool definitions in OpenAI format, or None if no tools.
        """
        tools = []

        # Add MCP tools
        for mcp_client in self.mcp_clients:
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                schema = tool.input_schema if tool.input_schema else {}
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": schema if schema else {"type": "object", "properties": {}},
                    },
                }
                tools.append(tool_def)

        # Add delegation tools for sub-agents (skip unavailable)
        for sub_agent in self.sub_agents.values():
            if not sub_agent._active:
                await sub_agent._init()

            if not sub_agent._active:
                logger.warning(
                    f"Sub-agent '{sub_agent.name}' is unavailable, skipping tool registration"
                )
                continue

            description = f"Delegate a task to the {sub_agent.name} agent."
            if sub_agent.agent_card:
                description = (
                    f"Delegate a task to the {sub_agent.agent_card.name} agent: "
                    f"{sub_agent.agent_card.description}"
                )

            tool_def = {
                "type": "function",
                "function": {
                    "name": f"{DELEGATION_TOOL_PREFIX}{sub_agent.name}",
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "The task to delegate to the agent.",
                            }
                        },
                        "required": ["task"],
                    },
                },
            }
            tools.append(tool_def)

        return tools if tools else None

    async def _get_string_mode_tools_prompt(self) -> Optional[str]:
        """Build text-based tools section for system prompt (string mode).

        Includes both MCP tools and sub-agent delegation tools in one list.
        Returns None if no tools available.
        """
        tools_desc = []

        # Add MCP tools
        for mcp_client in self.mcp_clients:
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                schema = tool.input_schema if tool.input_schema else {}
                params_str = json.dumps(schema, indent=2) if schema else "{}"
                tools_desc.append(
                    f"- **{tool.name}**: {tool.description}\n  Parameters: {params_str}"
                )

        # Add delegation tools (same delegate_to_ format as native mode)
        for sub_agent in self.sub_agents.values():
            if not sub_agent._active:
                await sub_agent._init()
            if sub_agent._active and sub_agent.agent_card:
                tool_name = f"{DELEGATION_TOOL_PREFIX}{sub_agent.name}"
                description = (
                    f"Delegate a task to the {sub_agent.agent_card.name} agent: "
                    f"{sub_agent.agent_card.description}"
                )
                tools_desc.append(
                    f"- **{tool_name}**: {description}\n"
                    f'  Parameters: {{"type": "object", "properties": '
                    f'{{"task": {{"type": "string", "description": "The task to delegate"}}}}, '
                    f'"required": ["task"]}}'
                )

        if not tools_desc:
            return None

        return "\n## Available Tools\n" + "\n".join(tools_desc) + "\n" + STRING_MODE_TOOLS_PROMPT

    @staticmethod
    def _parse_action(content: str) -> List[Dict[str, Any]]:
        """Parse tool call JSON from model response content (string mode).

        Supports two formats:
        - Array: {"tool_calls": [{"name": "x", "arguments": {...}}]}
        - Single (fallback): {"tool": "x", "arguments": {...}}

        Returns list of parsed tool call dicts, or empty list if none found.
        """
        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(content):
            pos = content.find("{", idx)
            if pos == -1:
                break
            try:
                parsed, end = decoder.raw_decode(content, pos)
                if isinstance(parsed, dict):
                    if "tool_calls" in parsed and isinstance(parsed["tool_calls"], list):
                        return [
                            tc
                            for tc in parsed["tool_calls"]
                            if isinstance(tc, dict) and tc.get("name")
                        ]
                    if "tool" in parsed:
                        return [parsed]
                idx = pos + end
            except json.JSONDecodeError:
                idx = pos + 1
        return []

    async def _build_system_prompt(self, user_system_prompt: Optional[str] = None) -> str:
        """Build system prompt for the agent.

        In string mode, includes text-based tool/agent descriptions.
        In native mode, tools are declared structurally via the API.
        """
        parts = []

        # Agent's core system prompt
        parts.append("## Agent System Prompt")
        parts.append(self.instructions)

        # String mode: add text-based tool descriptions (tools + delegation)
        if not self._supports_native_tools:
            tools_prompt = await self._get_string_mode_tools_prompt()
            if tools_prompt:
                parts.append(tools_prompt)

        # User-provided system prompt (if any)
        if user_system_prompt:
            parts.append("\n## User-Provided System Prompt")
            parts.append(user_system_prompt)
            parts.append(
                "\n*Note: The Agent System Prompt takes precedence for behavior and capabilities.*"
            )

        return "\n".join(parts)

    async def process_message(
        self,
        message: Union[str, List[Dict[str, str]]],
        session_id: Optional[str] = None,
        stream: bool = False,
        seed: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Process a message with agentic loop for tool calling and delegation.

        Yields:
            Content chunks (streaming) or single complete response (non-streaming)
        """
        # Reset mock responses at start of each request for fresh cycle
        self.model_api.reset_mock_responses()
        # Get or create session
        if session_id:
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        # Start agentic loop span
        span_attrs = {
            "agent.max_steps": self.max_steps,
            "stream": stream,
            ATTR_SESSION_ID: session_id,
        }
        if seed is not None:
            span_attrs["seed"] = seed
        otel.span_begin("agent.agentic_loop", attrs=span_attrs, metric_kind="request")
        span_failed = False
        try:
            # Extract user-provided system prompt (if any) from message array
            user_system_prompt: Optional[str] = None
            if isinstance(message, list):
                for msg in message:
                    if msg.get("role") == "system":
                        user_system_prompt = msg.get("content", "")
                        break

            # Build system prompt and tools parameter
            system_prompt = await self._build_system_prompt(user_system_prompt)
            tools = await self._build_tools_param()
            messages = [{"role": "system", "content": system_prompt}]

            # Handle both string and array input formats
            if isinstance(message, str):
                await self.memory.add_event(session_id, "user_message", message)
                messages.append({"role": "user", "content": message})
            else:
                for msg in message:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "system":
                        continue
                    if role == "task-delegation":
                        await self.memory.add_event(session_id, "task_delegation_received", content)
                        messages.append({"role": "user", "content": content})
                    else:
                        messages.append({"role": role, "content": content})
                        if role == "user":
                            await self.memory.add_event(session_id, "user_message", content)

            async for chunk in self._agentic_loop(
                messages,
                session_id,
                stream,
                seed=seed,
                tools=tools,
            ):
                yield chunk

        except Exception as e:
            span_failed = True
            logger.error(f"Error processing message: {str(e)}")
            otel.span_failure(e)
            await self.memory.add_event(session_id, "error", str(e))
            yield f"Sorry, I encountered an error: {str(e)}"
        finally:
            if not span_failed:
                otel.span_success()

    async def _agentic_loop(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
        stream: bool,
        seed: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """Execute the agentic loop with auto-detected tool calling mode.

        Phase 1: Action collection — model returns tool_calls (native) or JSON in
                 content (string) which are executed. Loops until no more actions.
        Phase 2: Final response — streaming/non-streaming model call for user output.
        """
        model_name = self.model_api.model if self.model_api else "unknown"
        tools_executed = False

        # Phase 1: Action Collection Loop
        phase1_active = self.max_steps > 0 and tools is not None

        if phase1_active:
            for step in range(self.max_steps):
                step_context = f"[Step {step + 1}/{self.max_steps}]"
                mode_label = "native" if self._supports_native_tools else "string"
                logger.debug(f"Agentic loop step {step + 1}/{self.max_steps} (mode={mode_label})")

                otel.span_begin(
                    f"agent.step.{step + 1}",
                    attrs={"step": step + 1, "max_steps": self.max_steps, "mode": mode_label},
                )
                step_failed = False
                try:
                    # Call model (with tools param only in native mode)
                    response = await self._call_model(
                        messages,
                        model_name,
                        seed=seed,
                        tools=tools if self._supports_native_tools else None,
                    )

                    # Extract tool calls from response
                    tool_calls = self._extract_tool_calls(response)

                    if not tool_calls:
                        # No actions — break to Phase 2
                        if not response.content:
                            logger.warning(
                                f"Model returned no tool_calls and no content at step {step + 1}"
                            )
                            await self.memory.add_event(
                                session_id,
                                "format_warning",
                                f"Model returned empty response at step {step + 1}",
                            )
                        break

                    # Build assistant message for conversation history
                    messages.append(self._build_assistant_msg(response, tool_calls))

                    # Execute tool calls
                    async for chunk in self._execute_tool_calls(
                        tool_calls,
                        messages,
                        session_id,
                        step,
                        step_context,
                    ):
                        yield chunk

                    tools_executed = True

                except Exception as e:
                    step_failed = True
                    otel.span_failure(e)
                    raise
                finally:
                    if not step_failed:
                        otel.span_success()
            else:
                max_steps_msg = f"Reached maximum reasoning steps ({self.max_steps})"
                logger.warning(max_steps_msg)
                yield max_steps_msg
                return

        # Phase 2: Final Response
        if tools_executed:
            messages.append(
                {
                    "role": "user",
                    "content": "Now provide your final response to the user based on the information gathered.",
                }
            )
        otel.span_begin("agent.response", attrs={"phase": "final", "stream": stream})
        final_failed = False
        try:
            if stream:
                full_response = ""
                async for chunk in self._call_model_streaming(messages, model_name, seed=seed):
                    full_response += chunk
                    yield chunk
                await self.memory.add_event(session_id, "agent_response", full_response)
            else:
                final_resp = await self._call_model(messages, model_name, seed=seed)
                content = final_resp.content or ""
                await self.memory.add_event(session_id, "agent_response", content)
                yield content
        except Exception as e:
            final_failed = True
            otel.span_failure(e)
            raise
        finally:
            if not final_failed:
                otel.span_success()

    def _extract_tool_calls(self, response: ModelResponse) -> List[ToolCall]:
        """Extract tool calls from model response.

        Checks response.tool_calls first (populated by native API or mock responses),
        then falls back to content JSON parsing for string mode.
        """
        # Use structured tool_calls if present (native mode or mock responses)
        if response.tool_calls:
            return response.tool_calls

        # String mode fallback: parse JSON from content
        if not self._supports_native_tools:
            content = response.content or ""
            actions = self._parse_action(content)
            tool_calls = []
            for i, action in enumerate(actions):
                # Support both {"name": ..} (tool_calls format) and {"tool": ..} (single format)
                tool_name = action.get("name") or action.get("tool", "")
                tool_args = action.get("arguments", {})
                if tool_name:
                    tool_calls.append(
                        ToolCall(
                            id=f"str_call_{hash(content) % 10000}_{i}",
                            name=tool_name,
                            arguments=tool_args,
                        )
                    )
            return tool_calls
        return []

    def _build_assistant_msg(
        self, response: ModelResponse, tool_calls: List[ToolCall]
    ) -> Dict[str, Any]:
        """Build assistant message for conversation history."""
        if self._supports_native_tools:
            return {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        return {"role": "assistant", "content": response.content or ""}

    async def _execute_tool_calls(
        self,
        tool_calls: List[ToolCall],
        messages: List[Dict[str, str]],
        session_id: str,
        step: int,
        step_context: str,
    ) -> AsyncIterator[str]:
        """Execute tool calls (regular + delegation) and append results to messages."""
        delegation_calls = [tc for tc in tool_calls if tc.name.startswith(DELEGATION_TOOL_PREFIX)]
        regular_calls = [tc for tc in tool_calls if not tc.name.startswith(DELEGATION_TOOL_PREFIX)]

        # Execute regular tool calls in parallel
        if regular_calls:
            for tc in regular_calls:
                await self.memory.add_event(
                    session_id,
                    "tool_call",
                    {"tool": tc.name, "arguments": tc.arguments},
                )
                yield json.dumps(
                    {
                        "type": "progress",
                        "step": step + 1,
                        "max_steps": self.max_steps,
                        "action": "tool_call",
                        "target": tc.name,
                    }
                )

            results = await asyncio.gather(
                *[self._execute_tool_with_result(tc, step_context) for tc in regular_calls]
            )
            for tc, (result_content, is_error) in zip(regular_calls, results):
                if not is_error:
                    await self.memory.add_event(
                        session_id,
                        "tool_result",
                        {"tool": tc.name, "result": result_content},
                    )
                else:
                    await self.memory.add_event(
                        session_id,
                        "tool_error",
                        {"tool": tc.name, "error": result_content},
                    )
                self._append_tool_result(
                    messages,
                    tc,
                    (
                        f"{step_context} Tool result: {json.dumps(result_content)}"
                        if not is_error
                        else f"{step_context} Tool execution failed: {result_content}"
                    ),
                )

        # Execute delegation calls sequentially
        for tc in delegation_calls:
            agent_name = tc.name[len(DELEGATION_TOOL_PREFIX) :]
            task = tc.arguments.get("task", "") if isinstance(tc.arguments, dict) else ""

            if not task:
                self._append_tool_result(
                    messages,
                    tc,
                    f"{step_context} Invalid delegation: missing 'task'",
                )
                continue

            await self.memory.add_event(
                session_id,
                "tool_call",
                {"tool": tc.name, "arguments": tc.arguments},
            )
            yield json.dumps(
                {
                    "type": "progress",
                    "step": step + 1,
                    "max_steps": self.max_steps,
                    "action": "delegate",
                    "target": agent_name,
                }
            )

            try:
                context_messages = [m for m in messages if m.get("role") != "system"]
                delegation_result = await self._execute_delegation(
                    agent_name,
                    task,
                    context_messages,
                    session_id,
                )
                self._append_tool_result(
                    messages,
                    tc,
                    f"{step_context} Agent response: {delegation_result}",
                )
            except ValueError as e:
                self._append_tool_result(
                    messages,
                    tc,
                    f"{step_context} Delegation failed: {e}",
                )

    async def _execute_tool_with_result(self, tc: ToolCall, step_context: str) -> tuple:
        """Execute a tool call and return (result, is_error)."""
        try:
            result = await self._execute_tool(tc.name, tc.arguments)  # type: ignore[arg-type]
            return (result, False)
        except Exception as e:
            return (str(e), True)

    def _append_tool_result(
        self,
        messages: List[Dict[str, str]],
        tc: ToolCall,
        content: str,
    ) -> None:
        """Append tool result to messages in the appropriate format."""
        if self._supports_native_tools:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        else:
            messages.append({"role": "user", "content": content})

    async def _call_model_streaming(
        self, messages: List[Dict[str, str]], model_name: str, seed: Optional[int] = None
    ) -> AsyncIterator[str]:
        """Call the model API with streaming and tracing."""
        otel.span_begin(
            "model.inference.stream",
            kind=SpanKind.CLIENT,
            attrs={ATTR_MODEL_NAME: model_name, "stream": True},
            metric_kind="model",
            metric_attrs={"model": model_name},
        )
        failed = False
        try:
            logger.debug(f"Model streaming call: {model_name}, messages count: {len(messages)}")
            response = await self.model_api.process_message(messages, stream=True, seed=seed)

            # response is an AsyncIterator when stream=True
            async for chunk in cast(AsyncIterator[str], response):
                yield chunk

        except Exception as e:
            failed = True
            logger.error(f"Model streaming call failed: {type(e).__name__}: {e}")
            otel.span_failure(e)
            raise
        finally:
            if not failed:
                otel.span_success()

    async def _call_model(
        self,
        messages: List[Dict[str, str]],
        model_name: str,
        seed: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ModelResponse:
        """Call the model API with tracing. Returns ModelResponse."""
        otel.span_begin(
            "model.inference",
            kind=SpanKind.CLIENT,
            attrs={ATTR_MODEL_NAME: model_name},
            metric_kind="model",
            metric_attrs={"model": model_name},
        )
        failed = False
        try:
            logger.debug(f"Model call: {model_name}, messages count: {len(messages)}")
            # Log the last user message for debugging
            for msg in reversed(messages):
                if msg.get("role") in ("user", "task-delegation", "tool"):
                    logger.debug(f"Model input (last msg): {msg.get('content', '')[:200]}...")
                    break
            response = await self.model_api.process_message(
                messages, stream=False, seed=seed, tools=tools
            )
            if isinstance(response, ModelResponse):
                logger.debug(
                    f"Model response: content={len(response.content or '')} chars, "
                    f"tool_calls={len(response.tool_calls)}"
                )
                if not response.content and not response.has_tool_calls:
                    logger.warning("Model returned response with neither content nor tool_calls")
                return response
            # Fallback for streaming iterator (shouldn't happen with stream=False)
            return ModelResponse(content=str(response), finish_reason="stop")
        except Exception as e:
            failed = True
            logger.error(f"Model call failed: {type(e).__name__}: {e}")
            otel.span_failure(e)
            raise
        finally:
            if not failed:
                otel.span_success()

    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """Execute a tool with tracing."""
        otel.span_begin(
            f"tool.{tool_name}",
            kind=SpanKind.CLIENT,
            attrs={ATTR_TOOL_NAME: tool_name},
            metric_kind="tool",
            metric_attrs={"tool": tool_name},
        )
        logger.debug(f"Executing tool: {tool_name}, args: {tool_args}")
        failed = False
        try:
            tool_result = None
            for mcp_client in self.mcp_clients:
                if tool_name in mcp_client._tools:
                    tool_result = await mcp_client.call_tool(tool_name, tool_args)
                    break

            if tool_result is None:
                raise ValueError(f"Tool '{tool_name}' not found")
            logger.debug(f"Tool {tool_name} result: {str(tool_result)[:200]}...")
            return tool_result
        except Exception as e:
            failed = True
            logger.error(f"Tool {tool_name} failed: {type(e).__name__}: {e}")
            otel.span_failure(e)
            raise
        finally:
            if not failed:
                otel.span_success()

    async def _execute_delegation(
        self,
        agent_name: str,
        task: str,
        context_messages: List[Dict[str, str]],
        session_id: str,
    ) -> str:
        """Execute delegation to a sub-agent with tracing."""
        otel.span_begin(
            f"delegate.{agent_name}",
            kind=SpanKind.CLIENT,
            attrs={ATTR_DELEGATION_TARGET: agent_name},
            metric_kind="delegation",
            metric_attrs={"target": agent_name},
        )
        logger.debug(f"Delegating to sub-agent: {agent_name}")
        logger.debug(f"Delegation task: {task[:200]}...")
        failed = False
        try:
            result = await self.delegate_to_sub_agent(
                agent_name, task, context_messages, session_id
            )
            logger.debug(f"Delegation to {agent_name} result: {result[:200]}...")
            return result
        except Exception as e:
            failed = True
            logger.error(f"Delegation to {agent_name} failed: {type(e).__name__}: {e}")
            otel.span_failure(e)
            raise
        finally:
            if not failed:
                otel.span_success()

    async def delegate_to_sub_agent(
        self,
        agent_name: str,
        task: str,
        context_messages: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Delegate a task to a sub-agent with context."""
        sub_agent = self.sub_agents.get(agent_name)
        if not sub_agent:
            raise ValueError(
                f"Sub-agent '{agent_name}' not found. Available: {list(self.sub_agents.keys())}"
            )

        if session_id:
            await self.memory.add_event(
                session_id, "delegation_request", {"agent": agent_name, "task": task}
            )

        # Build messages for sub-agent with context
        messages: List[Dict[str, str]] = []
        if context_messages:
            messages.extend(context_messages[-self.memory_context_limit :])
        messages.append({"role": "task-delegation", "content": task})

        try:
            response = await sub_agent.process_message(messages)

            if session_id:
                await self.memory.add_event(
                    session_id, "delegation_response", {"agent": agent_name, "response": response}
                )
            return response

        except RuntimeError as e:
            error_msg = str(e)
            logger.warning(f"Delegation to {agent_name} failed: {error_msg}")

            if session_id:
                await self.memory.add_event(
                    session_id, "delegation_error", {"agent": agent_name, "error": error_msg}
                )
            return f"[Delegation failed: {error_msg}]"

    async def get_agent_card(self, base_url: str) -> AgentCard:
        """Generate agent card for A2A discovery."""
        skills = []
        for mcp_client in self.mcp_clients:
            # Ensure MCP client is initialized to discover tools
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                skills.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                )

        capabilities = ["message_processing", "task_execution"]
        if self.mcp_clients:
            capabilities.append("tool_execution")
        if self.sub_agents:
            capabilities.append("task_delegation")

        return AgentCard(
            name=self.name,
            description=self.description,
            url=base_url,
            skills=skills,
            capabilities=capabilities,
        )

    async def close(self):
        """Close all connections and cleanup resources."""
        try:
            if hasattr(self.model_api, "close"):
                await self.model_api.close()
            for mcp_client in self.mcp_clients:
                if hasattr(mcp_client, "close"):
                    await mcp_client.close()
            for sub_agent in self.sub_agents.values():
                await sub_agent.close()
            logger.debug(f"Agent {self.name} closed successfully")
        except Exception as e:
            logger.warning(f"Error closing Agent {self.name}: {e}")
