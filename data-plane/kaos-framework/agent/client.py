"""
KAOS Agent client — Pydantic AI integration.

Wraps pydantic_ai.Agent with KAOS-specific functionality:
- Env-var driven configuration (operator injects AGENT_NAME, MODEL_API_URL, etc.)
- KAOS memory system (Local/Redis/Null) bridged to Pydantic AI message_history
- Sub-agent delegation as Pydantic AI tool functions
- MCP tool integration via Pydantic AI native MCPServerStreamableHTTP
- DEBUG_MOCK_RESPONSES support via custom FunctionModel
- OpenAI-compatible /v1/chat/completions API surface
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional, AsyncIterator, Union
from dataclasses import dataclass

import httpx
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse as PydanticModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from agent.memory import LocalMemory, NullMemory, RedisMemory
from telemetry.manager import (
    otel,
    KaosOtelManager,
    ATTR_SESSION_ID,
    ATTR_MODEL_NAME,
    ATTR_TOOL_NAME,
    ATTR_DELEGATION_TARGET,
)

logger = logging.getLogger(__name__)

Memory = LocalMemory | RedisMemory | NullMemory
DELEGATION_TOOL_PREFIX = "delegate_to_"


class _MockResponseState:
    """Mutable container for mock response state, shared via closure."""

    def __init__(self, template: List[str]):
        self.template = template
        self.responses: List[str] = []

    def reset(self):
        self.responses = list(self.template)


@dataclass
class AgentCard:
    """Agent discovery card for A2A protocol."""

    name: str
    description: str
    url: str
    skills: List[Dict[str, Any]]
    capabilities: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "skills": self.skills,
            "capabilities": self.capabilities,
        }


class RemoteAgent:
    """Remote agent client for A2A protocol with graceful degradation."""

    DISCOVERY_TIMEOUT = 5.0
    REQUEST_TIMEOUT = 60.0

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

    async def process_message(self, messages: List[Dict[str, str]]) -> str:
        """Process messages via remote agent's /v1/chat/completions."""
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")

        try:
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
        try:
            await self._discovery_client.aclose()
            await self._request_client.aclose()
        except Exception:
            pass


def _build_mock_model_function():
    """Build a FunctionModel handler from DEBUG_MOCK_RESPONSES env var.

    Returns (handler, state) tuple where state is used to reset per-request.
    Supports plain text and tool_calls JSON format.
    """
    raw = os.environ.get("DEBUG_MOCK_RESPONSES", "")
    if not raw:
        return None, None

    try:
        template = json.loads(raw)
        if not isinstance(template, list):
            template = [str(template)]
    except json.JSONDecodeError:
        template = [raw]

    state = _MockResponseState(template)

    def mock_handler(messages: list[ModelRequest], info: AgentInfo) -> PydanticModelResponse:
        if not state.responses:
            return PydanticModelResponse(parts=[TextPart(content="[no more mock responses]")])

        text = state.responses.pop(0)

        # Try to parse as tool_calls JSON
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "tool_calls" in parsed:
                parts = []
                for tc in parsed["tool_calls"]:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("arguments", {})
                    tool_id = tc.get("id", f"mock_{tool_name}")
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}
                    parts.append(
                        ToolCallPart(
                            tool_name=tool_name,
                            args=tool_args,
                            tool_call_id=tool_id,
                        )
                    )
                if parts:
                    return PydanticModelResponse(parts=parts)
        except (json.JSONDecodeError, TypeError):
            pass

        return PydanticModelResponse(parts=[TextPart(content=text)])

    return mock_handler, state


def reset_mock_responses():
    """Reset per-request mock response state. No-op if no mock model."""
    pass


class Agent:
    """KAOS Agent — wraps pydantic_ai.Agent with memory, delegation, and telemetry."""

    def __init__(
        self,
        name: str,
        model: Any = None,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: Optional[Memory] = None,
        sub_agents: Optional[List[RemoteAgent]] = None,
        mcp_servers: Optional[list] = None,
        max_steps: int = 5,
        memory_context_limit: int = 6,
        memory_enabled: bool = True,
        model_api_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.name = name
        self.instructions = instructions
        self.description = description
        self.memory: Memory = memory or LocalMemory()
        self.memory_context_limit = memory_context_limit
        self.memory_enabled = memory_enabled
        self.max_steps = max_steps
        self.sub_agents: Dict[str, RemoteAgent] = {
            agent.name: agent for agent in (sub_agents or [])
        }
        self._mcp_servers = mcp_servers or []
        self._mock_state: Optional[_MockResponseState] = None

        # Resolve the Pydantic AI model
        if model is not None:
            self._model = model
        else:
            mock_handler, mock_state = _build_mock_model_function()
            if mock_handler:
                self._model = FunctionModel(mock_handler)
                self._mock_state = mock_state
                logger.info(f"Agent {name}: using mock model (DEBUG_MOCK_RESPONSES)")
            elif model_api_url and model_name:
                # Ensure base_url includes /v1 for OpenAI-compatible endpoints
                # (Ollama serves at /v1/chat/completions, LiteLLM at /chat/completions)
                base_url = model_api_url.rstrip("/")
                if not base_url.endswith("/v1"):
                    base_url = f"{base_url}/v1"
                provider = OpenAIProvider(base_url=base_url, api_key="not-needed")
                self._model = OpenAIChatModel(model_name=model_name, provider=provider)
                logger.info(f"Agent {name}: using OpenAI model {model_name} at {base_url}")
            else:
                raise ValueError(
                    "Agent requires either 'model', 'model_api_url'+'model_name', "
                    "or DEBUG_MOCK_RESPONSES env var"
                )

        # Build the Pydantic AI agent
        self._agent = PydanticAgent(
            model=self._model,
            instructions=instructions,
            name=name,
            retries=max_steps,
            defer_model_check=True,
            toolsets=self._mcp_servers if self._mcp_servers else None,
        )

        # Register delegation tools for sub-agents
        self._register_delegation_tools()

        logger.info(
            f"Agent initialized: {name} (sub_agents={list(self.sub_agents.keys())}, "
            f"mcp_servers={len(self._mcp_servers)})"
        )

    def _register_delegation_tools(self):
        """Register delegate_to_{name} tools on the Pydantic AI agent."""
        for sub_agent_name, sub_agent in self.sub_agents.items():
            description = f"Delegate a task to the {sub_agent_name} agent."
            if sub_agent.agent_card:
                description = (
                    f"Delegate a task to the {sub_agent.agent_card.name} agent: "
                    f"{sub_agent.agent_card.description}"
                )
            tool_name = f"{DELEGATION_TOOL_PREFIX}{sub_agent_name}"

            # Capture sub_agent in closure
            _sub = sub_agent
            _name = sub_agent_name

            @self._agent.tool_plain(name=tool_name, description=description)
            async def _delegate(task: str, _s=_sub, _n=_name) -> str:
                return await self._execute_delegation(_n, task, _s)

    async def _execute_delegation(self, agent_name: str, task: str, sub_agent: RemoteAgent) -> str:
        """Execute delegation to a sub-agent."""
        otel.span_begin(
            f"delegate.{agent_name}",
            attrs={ATTR_DELEGATION_TARGET: agent_name},
            metric_kind="delegation",
            metric_attrs={"target": agent_name},
        )
        failed = False
        try:
            messages: List[Dict[str, str]] = [{"role": "task-delegation", "content": task}]
            result = await sub_agent.process_message(messages)
            return result
        except Exception as e:
            failed = True
            logger.error(f"Delegation to {agent_name} failed: {type(e).__name__}: {e}")
            otel.span_failure(e)
            return f"[Delegation failed: {e}]"
        finally:
            if not failed:
                otel.span_success()

    async def process_message(
        self,
        message: Union[str, List[Dict[str, str]]],
        session_id: Optional[str] = None,
        stream: bool = False,
        seed: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Process a message using Pydantic AI agent.

        Yields content chunks (streaming) or single complete response.
        """
        if self._mock_state:
            self._mock_state.reset()

        # Get or create session
        if session_id:
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        span_attrs = {
            "agent.max_steps": self.max_steps,
            "stream": stream,
            ATTR_SESSION_ID: session_id,
        }
        otel.span_begin("agent.agentic_loop", attrs=span_attrs, metric_kind="request")
        span_failed = False

        try:
            # Extract user prompt from message
            user_prompt = self._extract_user_prompt(message)

            # Detect delegation: check if message has task-delegation role
            is_delegation = False
            if isinstance(message, list):
                is_delegation = any(msg.get("role") == "task-delegation" for msg in message)

            # Store incoming message event
            event_type = "task_delegation_received" if is_delegation else "user_message"
            await self.memory.add_event(session_id, event_type, user_prompt)

            # Build message history from memory for context
            message_history = await self._build_message_history(session_id)

            if stream:
                full_response = ""
                async with self._agent.run_stream(
                    user_prompt, message_history=message_history
                ) as result:
                    async for chunk in result.stream_text(delta=True):
                        full_response += chunk
                        yield chunk
                await self.memory.add_event(session_id, "agent_response", full_response)
            else:
                result = await self._agent.run(user_prompt, message_history=message_history)
                content = str(result.output) if result.output else ""
                await self.memory.add_event(session_id, "agent_response", content)

                # Store new messages from Pydantic AI into memory
                for msg in result.new_messages():
                    await self._store_pydantic_message(session_id, msg)

                yield content

        except Exception as e:
            span_failed = True
            logger.error(f"Error processing message: {str(e)}")
            otel.span_failure(e)
            await self.memory.add_event(session_id, "error", str(e))
            yield f"Sorry, I encountered an error: {str(e)}"
        finally:
            if not span_failed:
                otel.span_success()

    def _extract_user_prompt(self, message: Union[str, List[Dict[str, str]]]) -> str:
        """Extract user prompt from string or message array."""
        if isinstance(message, str):
            return message
        for msg in reversed(message):
            role = msg.get("role", "user")
            if role in ("user", "task-delegation"):
                return msg.get("content", "")
        return ""

    async def _build_message_history(self, session_id: str) -> Optional[list]:
        """Build Pydantic AI message_history from KAOS memory events.

        Returns None if no history, otherwise a list of ModelRequest/ModelResponse.
        """
        events = await self.memory.get_session_events(session_id)
        if not events or len(events) <= 1:
            return None

        # Convert memory events to Pydantic AI message format (excluding latest)
        history: list = []
        for event in events[:-1]:
            if event.event_type == "user_message":
                history.append(ModelRequest(parts=[UserPromptPart(content=str(event.content))]))
            elif event.event_type == "agent_response":
                history.append(PydanticModelResponse(parts=[TextPart(content=str(event.content))]))
        return history if history else None

    async def _store_pydantic_message(self, session_id: str, msg: Any) -> None:
        """Store a Pydantic AI message as KAOS memory events."""
        if isinstance(msg, PydanticModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    is_delegation = part.tool_name.startswith("delegate_to_")
                    event_type = "delegation_request" if is_delegation else "tool_call"
                    await self.memory.add_event(
                        session_id,
                        event_type,
                        {"tool": part.tool_name, "arguments": part.args},
                    )
                elif isinstance(part, TextPart):
                    pass  # Final text is stored separately
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    is_delegation = part.tool_name.startswith("delegate_to_")
                    event_type = "delegation_response" if is_delegation else "tool_result"
                    result_content = part.content
                    if isinstance(result_content, (dict, list)):
                        result_value = result_content
                    elif isinstance(result_content, str):
                        try:
                            result_value = json.loads(result_content)
                        except (json.JSONDecodeError, ValueError):
                            result_value = result_content
                    else:
                        result_value = str(result_content)
                    await self.memory.add_event(
                        session_id,
                        event_type,
                        {"tool": part.tool_name, "result": result_value},
                    )

    async def get_agent_card(self, base_url: str) -> AgentCard:
        """Generate agent card for A2A discovery."""
        capabilities = ["message_processing", "task_execution"]
        if self._mcp_servers:
            capabilities.append("tool_execution")
        if self.sub_agents:
            capabilities.append("task_delegation")

        # Discover tools from MCP servers for skills list
        skills: list = []
        for mcp_server in self._mcp_servers:
            try:
                async with mcp_server:
                    tools = await mcp_server.list_tools()
                    for tool in tools:
                        skills.append({"name": tool.name, "description": tool.description or ""})
            except Exception as e:
                logger.warning(f"Failed to list tools from MCP server: {e}")

        # Add delegation tools as skills
        for agent_name in self.sub_agents:
            skills.append(
                {
                    "name": f"delegate_to_{agent_name}",
                    "description": f"Delegate task to {agent_name}",
                }
            )

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
            for sub_agent in self.sub_agents.values():
                await sub_agent.close()
            if hasattr(self.memory, "close"):
                await self.memory.close()  # type: ignore[operator]
            logger.debug(f"Agent {self.name} closed successfully")
        except Exception as e:
            logger.warning(f"Error closing Agent {self.name}: {e}")
