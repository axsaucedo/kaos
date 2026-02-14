"""
Agent client implementation for OpenAI-compatible API.

Clean, simple implementation with proper streaming support and tool integration.
Includes agentic loop for tool calling and agent delegation.
Instrumented with OpenTelemetry for tracing and metrics.

Key design principles:
- Agent decides when to delegate/call tools based on model response
- Server only routes requests, never interprets delegation
- DEBUG_MOCK_RESPONSES env var handled by ModelAPI for testing
- RemoteAgent.process_message() uses /v1/chat/completions
"""

import json
import logging
from typing import List, Dict, Any, Optional, AsyncIterator, Union, cast
import httpx
from dataclasses import dataclass

from modelapi.client import ModelAPI
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

# System prompt templates for agentic loop
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
        function_calling: str = "text",
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
        self.function_calling = function_calling

        logger.info(f"Agent initialized: {name}")

    async def _get_tools_prompt(self) -> Optional[str]:
        """Build complete tools section for system prompt.

        Returns:
            Complete tools section with header and instructions, or None if no tools.
        """
        if not self.mcp_clients:
            return None

        tools_desc = []
        for mcp_client in self.mcp_clients:
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                # Use input_schema (MCP standard) for parameter description
                schema = tool.input_schema if tool.input_schema else {}
                params_str = json.dumps(schema, indent=2) if schema else "{}"
                tools_desc.append(
                    f"- **{tool.name}**: {tool.description}\n  Parameters: {params_str}"
                )

        if not tools_desc:
            return None

        return "\n## Available Tools\n" + "\n".join(tools_desc) + "\n" + TOOLS_INSTRUCTIONS

    async def _get_agents_prompt(self) -> Optional[str]:
        """Build complete agents section for system prompt.

        Returns:
            Complete agents section with header and instructions, or None if no agents.
        """
        if not self.sub_agents:
            return None

        available = []
        unavailable = []

        for sub_agent in self.sub_agents.values():
            if not sub_agent._active:
                await sub_agent._init()

            if sub_agent._active and sub_agent.agent_card:
                available.append(
                    f"- **{sub_agent.agent_card.name}**: {sub_agent.agent_card.description}"
                )
            else:
                unavailable.append(f"- **{sub_agent.name}**: (unavailable)")

        if not available and not unavailable:
            return None

        parts = available
        if unavailable:
            parts.append("\n**Unavailable agents:**")
            parts.extend(unavailable)

        return (
            "\n## Available Agents for Delegation\n" + "\n".join(parts) + "\n" + AGENT_INSTRUCTIONS
        )

    async def _get_tools_for_api(self) -> List[dict]:
        """Convert MCP tools and sub-agents to OpenAI tools format for native function calling."""
        tools: List[dict] = []

        # Convert MCP tools
        for mcp_client in self.mcp_clients:
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.input_schema,
                        },
                    }
                )

        # Register sub-agents as pseudo-tools
        for agent_name, sub_agent in self.sub_agents.items():
            description = ""
            if sub_agent.agent_card:
                description = sub_agent.agent_card.description
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"delegate_to_{agent_name}",
                        "description": f"Delegate a task to the {agent_name} sub-agent. {description}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "task": {
                                    "type": "string",
                                    "description": "The task to delegate to the sub-agent",
                                }
                            },
                            "required": ["task"],
                        },
                    },
                }
            )

        return tools

    def _is_delegation_call(self, tool_name: str) -> Optional[str]:
        """Check if tool call is a delegation pseudo-tool. Returns agent name or None."""
        if tool_name.startswith("delegate_to_"):
            return tool_name[len("delegate_to_") :]
        return None

    async def _build_system_prompt(self, user_system_prompt: Optional[str] = None) -> str:
        """Build enhanced system prompt with tools, agents info, and optional user prompt.

        Args:
            user_system_prompt: Optional user-provided system prompt to merge.

        Returns:
            Complete system prompt with clear section markers.
        """
        parts = []

        # Agent's core system prompt
        parts.append("## Agent System Prompt")
        parts.append(self.instructions)

        tools_prompt = await self._get_tools_prompt()
        if tools_prompt:
            parts.append(tools_prompt)

        agents_prompt = await self._get_agents_prompt()
        if agents_prompt:
            parts.append(agents_prompt)

        # Add no-action instruction if we have tools or agents
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

    def _parse_action(self, content: str) -> Dict[str, Any]:
        """Parse action JSON from model response.

        Looks for a JSON object anywhere in the response that represents an action.
        The model can include reasoning/context before or after the JSON.
        Returns the parsed action dict, or empty dict if no valid action found.

        Action formats:
        - Tool call: {"tool": "name", "arguments": {...}}
        - Delegation: {"agent": "name", "task": "..."}
        - No action: {}
        """
        content = content.strip()

        # Try to parse the entire content as JSON first (pure JSON response)
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Look for JSON objects in the content (may have surrounding text)
        # Find all potential JSON objects using brace matching
        i = 0
        while i < len(content):
            if content[i] == "{":
                # Find matching closing brace
                depth = 0
                start = i
                for j in range(i, len(content)):
                    if content[j] == "{":
                        depth += 1
                    elif content[j] == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = content[start : j + 1]
                            try:
                                parsed = json.loads(candidate)
                                if isinstance(parsed, dict):
                                    # Check if it's a valid action (tool, agent, or empty)
                                    if "tool" in parsed or "agent" in parsed or parsed == {}:
                                        return parsed
                            except json.JSONDecodeError:
                                pass
                            break
            i += 1

        return {}

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

            # Build enhanced system prompt with tools/agents info
            system_prompt = await self._build_system_prompt(user_system_prompt)
            logger.debug(f"System prompt built ({len(system_prompt)} chars)")
            logger.debug(f"System prompt preview: {system_prompt[:300]}...")
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
            async for chunk in self._agentic_loop(messages, session_id, stream, seed=seed):
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
    ) -> AsyncIterator[str]:
        """Execute the two-phase agentic loop with tracing.

        Phase 1: Action collection - non-streaming model calls to collect tool/delegation results
        Phase 2: Final response - streaming model call to produce the user-visible response
        """
        model_name = self.model_api.model if self.model_api else "unknown"

        def _step_context(step: int) -> str:
            """Generate step context metadata for the model."""
            return f"[Step {step + 1}/{self.max_steps}]"

        # Phase 1: Action Collection Loop
        for step in range(self.max_steps):
            logger.debug(f"Agentic loop step {step + 1}/{self.max_steps}")

            # Start step span
            step_attrs = {"step": step + 1, "max_steps": self.max_steps, "phase": "action"}
            otel.span_begin(f"agent.step.{step + 1}", attrs=step_attrs)
            step_failed = False
            try:
                # Get model response (non-streaming for action collection)
                content = await self._call_model(messages, model_name, seed=seed)

                # Parse action from response
                action = self._parse_action(content)

                # Check for tool call
                if action.get("tool"):
                    tool_name = action["tool"]
                    tool_args = action.get("arguments", {})

                    await self.memory.add_event(session_id, "tool_call", action)

                    # Emit progress block
                    progress = json.dumps(
                        {
                            "type": "progress",
                            "step": step + 1,
                            "max_steps": self.max_steps,
                            "action": "tool_call",
                            "target": tool_name,
                        }
                    )
                    yield progress

                    try:
                        tool_result = await self._execute_tool(tool_name, tool_args)

                        await self.memory.add_event(
                            session_id, "tool_result", {"tool": tool_name, "result": tool_result}
                        )

                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"{_step_context(step)} Tool result: {json.dumps(tool_result)}",
                            }
                        )
                        continue

                    except Exception as e:
                        error_msg = str(e)
                        await self.memory.add_event(
                            session_id, "tool_error", {"tool": tool_name, "error": error_msg}
                        )
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"{_step_context(step)} Tool execution failed: {error_msg}",
                            }
                        )
                        continue

                # Check for delegation
                if action.get("agent"):
                    agent_name = action["agent"]
                    task = action.get("task", "")

                    if not task:
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"{_step_context(step)} Invalid delegation: missing 'task'",
                            }
                        )
                        continue

                    # Emit progress block
                    progress = json.dumps(
                        {
                            "type": "progress",
                            "step": step + 1,
                            "max_steps": self.max_steps,
                            "action": "delegate",
                            "target": agent_name,
                        }
                    )
                    yield progress

                    try:
                        context_messages = [m for m in messages if m.get("role") != "system"]

                        delegation_result = await self._execute_delegation(
                            agent_name, task, context_messages, session_id
                        )

                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"{_step_context(step)} Agent response: {delegation_result}",
                            }
                        )
                        continue

                    except ValueError as e:
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"{_step_context(step)} Delegation failed: {e}",
                            }
                        )
                        continue

                # No action (empty dict or no recognized action) - proceed to Phase 2
                break

            except Exception as e:
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

        # Phase 2: Final Response (streaming)
        otel.span_begin("agent.response", attrs={"phase": "final", "stream": stream})
        final_failed = False
        try:
            # Add instruction to provide final response
            messages.append(
                {"role": "user", "content": "Now provide your final response to the user."}
            )

            if stream:
                # True streaming from model
                full_response = ""
                async for chunk in self._call_model_streaming(messages, model_name, seed=seed):
                    full_response += chunk
                    yield chunk

                # Record the complete response in memory
                await self.memory.add_event(session_id, "agent_response", full_response)
            else:
                # Non-streaming final response
                content = await self._call_model(messages, model_name, seed=seed)
                await self.memory.add_event(session_id, "agent_response", content)
                yield content

        except Exception as e:
            final_failed = True
            otel.span_failure(e)
            raise
        finally:
            if not final_failed:
                otel.span_success()

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
        self, messages: List[Dict[str, str]], model_name: str, seed: Optional[int] = None
    ) -> str:
        """Call the model API with tracing."""
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
                if msg.get("role") in ("user", "task-delegation"):
                    logger.debug(f"Model input (last user msg): {msg.get('content', '')[:200]}...")
                    break
            content = cast(
                str, await self.model_api.process_message(messages, stream=False, seed=seed)
            )
            logger.debug(f"Model response ({len(content)} chars): {content[:200]}...")
            return content
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
