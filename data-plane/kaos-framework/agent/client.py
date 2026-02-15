"""
Agent client implementation for OpenAI-compatible API.

Clean, simple implementation with proper streaming support and tool integration.
Includes agentic loop with dual-mode tool calling:
- native: Uses OpenAI tools API for structured function calling
- string: Uses text-based JSON parsing from model content
- auto: Tries native first, falls back to string on unsupported models
Instrumented with OpenTelemetry for tracing and metrics.

Key design principles:
- Agent supports native, string, and auto tool call modes
- Sub-agent delegation exposed as delegate_to_{name} tool functions
- Server only routes requests, never interprets delegation
- DEBUG_MOCK_RESPONSES env var handled by ModelAPI for testing
- RemoteAgent.process_message() uses /v1/chat/completions
"""

import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional, AsyncIterator, Union, cast
import httpx
from dataclasses import dataclass

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

# Valid tool call modes
TOOL_CALL_MODES = ("auto", "native", "string")

# System prompt templates for string-mode tool calling
TOOLS_INSTRUCTIONS = """
To use a tool, include this JSON in your response:
{"tool": "tool_name", "arguments": {"arg1": "value1"}}

You may include reasoning or context before/after the JSON.
Wait for the tool result before providing your final answer.
"""

AGENT_INSTRUCTIONS = """
To delegate a task to another agent, include this JSON in your response:
{"agent": "agent_name", "task": "task description"}

You may include reasoning or context before/after the JSON.
Wait for the agent's response before providing your final answer.
"""

NO_ACTION_INSTRUCTIONS = """
When you have all the information needed to provide a final answer, include:
{}

Then the system will ask you to provide your final response.
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

        if tool_call_mode not in TOOL_CALL_MODES:
            logger.warning(f"Invalid tool_call_mode '{tool_call_mode}', defaulting to 'auto'")
            tool_call_mode = "auto"
        self.tool_call_mode = tool_call_mode
        # For auto mode, tracks resolved mode after first attempt
        self._resolved_tool_call_mode: Optional[str] = None

        logger.info(f"Agent initialized: {name} (tool_call_mode={self.tool_call_mode})")

    def _get_effective_mode(self) -> str:
        """Get the effective tool call mode, considering auto-mode resolution."""
        if self.tool_call_mode == "auto":
            return self._resolved_tool_call_mode or "native"
        return self.tool_call_mode

    @staticmethod
    def _is_tools_not_supported_error(exc: Exception) -> bool:
        """Check if an exception indicates the model doesn't support native tool calling."""
        error_text = str(exc).lower()
        keywords = ["tool", "function", "tools", "function_call", "function calling"]
        status_match = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
            400,
            422,
        )
        keyword_match = any(kw in error_text for kw in keywords)
        return status_match and keyword_match

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

    async def _get_tools_prompt(self) -> Optional[str]:
        """Build text-based tools section for system prompt (string mode).

        Returns:
            Complete tools section with descriptions and instructions, or None if no tools.
        """
        if not self.mcp_clients:
            return None

        tools_desc = []
        for mcp_client in self.mcp_clients:
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                schema = tool.input_schema if tool.input_schema else {}
                params_str = json.dumps(schema, indent=2) if schema else "{}"
                tools_desc.append(
                    f"- **{tool.name}**: {tool.description}\n  Parameters: {params_str}"
                )

        if not tools_desc:
            return None

        return "\n## Available Tools\n" + "\n".join(tools_desc) + "\n" + TOOLS_INSTRUCTIONS

    async def _get_agents_prompt(self) -> Optional[str]:
        """Build text-based agents section for system prompt (string mode).

        Returns:
            Complete agents section with descriptions and instructions, or None if no agents.
        """
        if not self.sub_agents:
            return None

        available = []
        for sub_agent in self.sub_agents.values():
            if not sub_agent._active:
                await sub_agent._init()

            if sub_agent._active and sub_agent.agent_card:
                available.append(
                    f"- **{sub_agent.agent_card.name}**: {sub_agent.agent_card.description}"
                )

        if not available:
            return None

        return (
            "\n## Available Agents for Delegation\n"
            + "\n".join(available)
            + "\n"
            + AGENT_INSTRUCTIONS
        )

    def _parse_action(self, content: str) -> Dict[str, Any]:
        """Parse action JSON from model response content (string mode).

        Looks for JSON objects in the response that represent tool calls or delegations.
        Returns the parsed action dict, or empty dict if no valid action found.

        Action formats:
        - Tool call: {"tool": "name", "arguments": {...}}
        - Delegation: {"agent": "name", "task": "..."}
        - No action: {}
        """
        content = content.strip()

        # Try to parse the entire content as JSON first
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Find JSON objects in content using brace matching
        i = 0
        while i < len(content):
            if content[i] == "{":
                depth = 0
                start = i
                in_string = False
                escape_next = False
                for j in range(i, len(content)):
                    if escape_next:
                        escape_next = False
                        continue
                    if content[j] == "\\":
                        escape_next = True
                        continue
                    if content[j] == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if content[j] == "{":
                        depth += 1
                    elif content[j] == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = content[start : j + 1]
                            try:
                                parsed = json.loads(candidate)
                                if isinstance(parsed, dict):
                                    return parsed
                            except json.JSONDecodeError:
                                pass
                            break
                i += 1
            else:
                i += 1

        return {}

    async def _build_system_prompt(self, user_system_prompt: Optional[str] = None) -> str:
        """Build system prompt for the agent.

        In string mode, includes text-based tool/agent descriptions and instructions.
        In native mode, tools are declared structurally via the API.

        Args:
            user_system_prompt: Optional user-provided system prompt to merge.

        Returns:
            Complete system prompt.
        """
        effective_mode = self._get_effective_mode()
        parts = []

        # Agent's core system prompt
        parts.append("## Agent System Prompt")
        parts.append(self.instructions)

        # String mode: add text-based tool/agent prompts
        if effective_mode == "string":
            tools_prompt = await self._get_tools_prompt()
            if tools_prompt:
                parts.append(tools_prompt)

            agents_prompt = await self._get_agents_prompt()
            if agents_prompt:
                parts.append(agents_prompt)

            if tools_prompt or agents_prompt:
                parts.append(NO_ACTION_INSTRUCTIONS)

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

        Args:
            message: User message to process - can be a string or OpenAI-style message array
            session_id: Optional session ID (created if not provided)
            stream: Whether to stream the response
            seed: Optional seed for reproducible generation

        Yields:
            Content chunks (streaming) or single complete response (non-streaming)

        Note:
            For testing, set DEBUG_MOCK_RESPONSES env var to a JSON array of responses
            that will be used instead of calling the model API.
        """
        # Reset mock responses at start of each request for fresh cycle
        self.model_api.reset_mock_responses()
        # Get or create session
        if session_id:
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        # Start agentic loop span (INTERNAL - FastAPI auto-instruments SERVER span)
        span_attrs = {
            "agent.max_steps": self.max_steps,
            "stream": stream,
            ATTR_SESSION_ID: session_id,
        }
        if seed is not None:
            span_attrs["seed"] = seed
        otel.span_begin(
            "agent.agentic_loop",
            attrs=span_attrs,
            metric_kind="request",
        )
        # Use failed flag pattern to ensure spans close on return/yield/early exit
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
            tools_param = await self._build_tools_param()
            logger.debug(f"System prompt built ({len(system_prompt)} chars)")
            logger.debug(f"Tools param: {len(tools_param) if tools_param else 0} tools")
            messages = [{"role": "system", "content": system_prompt}]

            # Handle both string and array input formats
            if isinstance(message, str):
                logger.debug(f"User message: {message[:200]}...")
                await self.memory.add_event(session_id, "user_message", message)
                messages.append({"role": "user", "content": message})
            else:
                for msg in message:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "system":
                        continue  # Already captured above

                    if role == "task-delegation":
                        logger.debug(f"Received delegation task: {content[:200]}...")
                        await self.memory.add_event(session_id, "task_delegation_received", content)
                        messages.append({"role": "user", "content": content})
                    else:
                        messages.append({"role": role, "content": content})
                        if role == "user":
                            logger.debug(f"User message: {content[:200]}...")
                            await self.memory.add_event(session_id, "user_message", content)

            # Agentic loop - iterate up to max_steps
            logger.debug(f"Starting agentic loop with {len(messages)} messages")

            # Determine effective mode and tools param for agentic loop
            effective_mode = self._get_effective_mode()
            loop_tools = tools_param if effective_mode == "native" else None
            # In string mode, we still need to know if tools exist for Phase 1 gating
            has_tools = tools_param is not None

            async for chunk in self._agentic_loop(
                messages,
                session_id,
                stream,
                seed=seed,
                tools=loop_tools,
                has_tools=has_tools,
            ):
                yield chunk

        except Exception as e:
            span_failed = True
            error_msg = f"Error processing message: {str(e)}"
            logger.error(error_msg)
            otel.span_failure(e)
            await self.memory.add_event(session_id, "error", error_msg)
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
        has_tools: bool = False,
    ) -> AsyncIterator[str]:
        """Execute the agentic loop with native or string-based tool calling.

        Phase 1: Action collection - model returns tool_calls (native) or JSON in
                 content (string) which are executed. Loops until no more actions.
        Phase 2: Final response - streaming/non-streaming model call for user output.

        In auto mode, if native tool calling fails with a tools-not-supported error,
        the agent falls back to string mode and retries. The resolved mode is persisted
        so subsequent requests don't retry native.
        """
        model_name = self.model_api.model if self.model_api else "unknown"
        effective_mode = self._get_effective_mode()

        def _step_context(step: int) -> str:
            """Generate step context metadata for the model."""
            return f"[Step {step + 1}/{self.max_steps}]"

        # Track whether any tools/delegations were executed in Phase 1
        tools_executed = False

        # Phase 1: Action Collection Loop
        # Skip entirely if no tools available or max_steps is 0
        phase1_active = self.max_steps > 0 and (
            (effective_mode == "native" and tools is not None)
            or (effective_mode == "string" and has_tools)
        )

        if phase1_active:
            for step in range(self.max_steps):
                logger.debug(
                    f"Agentic loop step {step + 1}/{self.max_steps} (mode={effective_mode})"
                )

                # Start step span
                step_attrs = {
                    "step": step + 1,
                    "max_steps": self.max_steps,
                    "phase": "action",
                    "mode": effective_mode,
                }
                otel.span_begin(f"agent.step.{step + 1}", attrs=step_attrs)
                step_failed = False
                try:
                    if effective_mode == "native":
                        # Native path: pass tools param, read tool_calls from response
                        result = self._phase1_native_step(
                            messages, model_name, session_id, step, seed, tools
                        )
                    else:
                        # String path: no tools param, parse JSON from content
                        result = self._phase1_string_step(
                            messages, model_name, session_id, step, seed
                        )

                    should_continue = False
                    async for item in result:
                        if item == "__CONTINUE__":
                            should_continue = True
                            tools_executed = True
                        elif item == "__BREAK__":
                            pass  # will break after loop
                        else:
                            yield item

                    if should_continue:
                        continue
                    break

                except Exception as e:
                    # Auto-mode fallback: if native tools not supported, switch to string
                    if (
                        self.tool_call_mode == "auto"
                        and effective_mode == "native"
                        and self._is_tools_not_supported_error(e)
                    ):
                        logger.warning(
                            f"Native tool calling not supported by model, "
                            f"falling back to string mode: {e}"
                        )
                        self._resolved_tool_call_mode = "string"
                        effective_mode = "string"

                        # Rebuild system prompt with string-mode tool descriptions
                        new_system_prompt = await self._build_system_prompt()
                        messages[0] = {"role": "system", "content": new_system_prompt}

                        otel.span_success()
                        step_failed = True  # skip finally span_success
                        # Restart from step 0 in string mode — break and re-enter loop
                        break
                    step_failed = True
                    otel.span_failure(e)
                    raise
                finally:
                    if not step_failed:
                        otel.span_success()
            else:
                # Max steps reached without completing - yield warning and return
                max_steps_msg = f"Reached maximum reasoning steps ({self.max_steps})"
                logger.warning(max_steps_msg)
                yield max_steps_msg
                return

            # If we fell back to string mode, re-run Phase 1 loop
            if self.tool_call_mode == "auto" and effective_mode == "string" and not tools_executed:
                for step in range(self.max_steps):
                    logger.debug(
                        f"Agentic loop step {step + 1}/{self.max_steps} (mode=string, fallback)"
                    )
                    step_attrs = {
                        "step": step + 1,
                        "max_steps": self.max_steps,
                        "phase": "action",
                        "mode": "string",
                    }
                    otel.span_begin(f"agent.step.{step + 1}", attrs=step_attrs)
                    step_failed = False
                    try:
                        result = self._phase1_string_step(
                            messages, model_name, session_id, step, seed
                        )
                        should_continue = False
                        async for item in result:
                            if item == "__CONTINUE__":
                                should_continue = True
                                tools_executed = True
                            elif item == "__BREAK__":
                                pass
                            else:
                                yield item
                        if should_continue:
                            continue
                        break
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
        # Only inject context-gathering instruction when tools/delegations were executed
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

    async def _phase1_native_step(
        self,
        messages: List[Dict[str, str]],
        model_name: str,
        session_id: str,
        step: int,
        seed: Optional[int],
        tools: Optional[List[Dict[str, Any]]],
    ) -> AsyncIterator[str]:
        """Execute one native-mode Phase 1 step.

        Yields progress/data chunks and special signals:
        - "__CONTINUE__": indicates tool calls were executed, loop should continue
        - "__BREAK__": indicates no tool calls, loop should break to Phase 2
        """
        step_context = f"[Step {step + 1}/{self.max_steps}]"

        response = await self._call_model(messages, model_name, seed=seed, tools=tools)

        if response.has_tool_calls:
            # Add assistant message with ALL tool calls to conversation
            assistant_msg: Dict[str, Any] = {
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
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            # Separate delegation and regular tool calls
            delegation_calls = []
            regular_calls = []
            for tc in response.tool_calls:
                if tc.name.startswith(DELEGATION_TOOL_PREFIX):
                    delegation_calls.append(tc)
                else:
                    regular_calls.append(tc)

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

                tool_results = await asyncio.gather(
                    *[
                        self._execute_tool_with_memory(tc, session_id, step_context)
                        for tc in regular_calls
                    ]
                )
                messages.extend(tool_results)

            # Execute delegation calls sequentially
            for tc in delegation_calls:
                agent_name = tc.name[len(DELEGATION_TOOL_PREFIX) :]
                task = tc.arguments.get("task", "")

                if not task:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"{step_context} Invalid delegation: missing 'task'",
                        }
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
                        agent_name, task, context_messages, session_id
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"{step_context} Agent response: {delegation_result}",
                        }
                    )
                except ValueError as e:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"{step_context} Delegation failed: {e}",
                        }
                    )

            yield "__CONTINUE__"
            return

        # No tool calls - model wants to respond directly, proceed to Phase 2
        if not response.content:
            logger.warning(f"Model returned no tool_calls and no content at step {step + 1}")
            await self.memory.add_event(
                session_id,
                "format_warning",
                f"Model returned empty response at step {step + 1}",
            )
        yield "__BREAK__"

    async def _phase1_string_step(
        self,
        messages: List[Dict[str, str]],
        model_name: str,
        session_id: str,
        step: int,
        seed: Optional[int],
    ) -> AsyncIterator[str]:
        """Execute one string-mode Phase 1 step.

        Parses JSON actions from model content text. Uses user/assistant roles
        for tool results (no tool_call_id since there's no structured tool call).

        Yields progress/data chunks and special signals:
        - "__CONTINUE__": indicates action was found and executed
        - "__BREAK__": indicates no action found, loop should break
        """
        step_context = f"[Step {step + 1}/{self.max_steps}]"

        # No tools param for string mode
        response = await self._call_model(messages, model_name, seed=seed)
        content = response.content or ""

        # Parse action from response content
        action = self._parse_action(content)

        # Check for tool call
        if action.get("tool"):
            tool_name = action["tool"]
            tool_args = action.get("arguments", {})

            await self.memory.add_event(
                session_id, "tool_call", {"tool": tool_name, "arguments": tool_args}
            )

            yield json.dumps(
                {
                    "type": "progress",
                    "step": step + 1,
                    "max_steps": self.max_steps,
                    "action": "tool_call",
                    "target": tool_name,
                }
            )

            try:
                tool_result = await self._execute_tool(tool_name, tool_args)
                await self.memory.add_event(
                    session_id,
                    "tool_result",
                    {"tool": tool_name, "result": tool_result},
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"{step_context} Tool result: {json.dumps(tool_result)}",
                    }
                )
            except Exception as e:
                error_msg = str(e)
                await self.memory.add_event(
                    session_id,
                    "tool_error",
                    {"tool": tool_name, "error": error_msg},
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"{step_context} Tool execution failed: {error_msg}",
                    }
                )

            yield "__CONTINUE__"
            return

        # Check for delegation
        if action.get("agent"):
            agent_name = action["agent"]
            task = action.get("task", "")

            if not task:
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"{step_context} Invalid delegation: missing 'task'",
                    }
                )
                yield "__CONTINUE__"
                return

            await self.memory.add_event(
                session_id,
                "tool_call",
                {"tool": f"delegate_to_{agent_name}", "arguments": {"task": task}},
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
                    agent_name, task, context_messages, session_id
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"{step_context} Agent response: {delegation_result}",
                    }
                )
            except ValueError as e:
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"{step_context} Delegation failed: {e}",
                    }
                )

            yield "__CONTINUE__"
            return

        # No action (empty dict or no recognized action) - proceed to Phase 2
        yield "__BREAK__"

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

    async def _execute_tool_with_memory(
        self, tc: ToolCall, session_id: str, step_context: str
    ) -> Dict[str, Any]:
        """Execute a tool call and record result/error in memory.

        Returns a role='tool' message dict for appending to conversation.
        """
        try:
            result = await self._execute_tool(tc.name, tc.arguments)  # type: ignore[arg-type]
            await self.memory.add_event(
                session_id,
                "tool_result",
                {"tool": tc.name, "result": result},
            )
            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": f"{step_context} Tool result: {json.dumps(result)}",
            }
        except Exception as e:
            error_msg = str(e)
            await self.memory.add_event(
                session_id,
                "tool_error",
                {"tool": tc.name, "error": error_msg},
            )
            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": f"{step_context} Tool execution failed: {error_msg}",
            }

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
