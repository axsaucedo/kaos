"""Data classes, settings, and model resolution for KAOS agent framework."""

import os
import json
import time
import logging
from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings
import httpx

from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse as PydanticModelResponse,
    TextPart,
    ToolCallPart,
)
from opentelemetry.propagate import inject

if TYPE_CHECKING:
    from pais.memory import Memory, MemoryScope

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    """Per-run dependencies passed via RunContext to tools."""

    session_id: str = ""
    memory: Optional["Memory"] = None
    # Non-secret request security context (request_id/session_id/principal/actor/scopes)
    # Populated by the identity runtime for audit/correlation; never carries raw bearer tokens.
    security_context: Optional[Dict[str, Any]] = None
    # Server-derived memory scope for this run (principal/agent/session owner).
    memory_scope: Optional["MemoryScope"] = None


class _MockResponseState:
    """Mutable container for mock response state, shared via closure."""

    def __init__(self, template: List[str]):
        self.template = template
        self.responses: List[str] = []

    def reset(self):
        self.responses = list(self.template)


class AgentCardCapabilities(BaseModel):
    """A2A agent card capabilities."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    streaming: bool = True
    push_notifications: bool = False
    state_transition_history: bool = False


class AgentCardSkill(BaseModel):
    """A2A agent card skill."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    name: str
    description: str
    tags: list[str] = []
    input_modes: list[str] = ["application/json"]
    output_modes: list[str] = ["application/json"]


class AgentCard(BaseModel):
    """A2A-compliant agent discovery card."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    description: str
    url: str
    version: str
    protocol_version: str = "0.3.0"
    skills: list[AgentCardSkill] = []
    capabilities: AgentCardCapabilities = AgentCardCapabilities()
    supported_protocols: list[str] = ["jsonrpc"]
    default_input_modes: list[str] = ["application/json"]
    default_output_modes: list[str] = ["application/json"]

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


class RemoteAgent:
    """Remote agent client for A2A protocol with graceful degradation."""

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
        self._supports_a2a = False
        self._client = httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT)
        logger.info(f"RemoteAgent initialized: {name} -> {url}")

    async def _init(self) -> bool:
        """Fetch agent card and activate. Returns True if successful."""
        try:
            response = await self._client.get(f"{self.card_url}/.well-known/agent.json")
            response.raise_for_status()
            data = response.json()
            self.agent_card = AgentCard(
                name=data.get("name", self.name),
                description=data.get("description", ""),
                url=self.card_url,
                version=data.get("version", "unknown"),
                skills=[AgentCardSkill(**s) for s in data.get("skills", [])],
                capabilities=AgentCardCapabilities(**data.get("capabilities", {})),
            )
            protocols = data.get("supportedProtocols", [])
            self._supports_a2a = "jsonrpc" in protocols
            self._active = True
            logger.info(
                f"RemoteAgent {self.name} active: a2a={self._supports_a2a}, {self.agent_card.description}"
            )
            return True
        except Exception as e:
            self._active = False
            logger.warning(f"RemoteAgent {self.name} init failed: {type(e).__name__}: {e}")
            return False

    async def process_message(self, messages: List[Dict[str, str]]) -> str:
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")

        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break

        if self._supports_a2a and last_user_msg:
            try:
                return await self._send_a2a_message(last_user_msg)
            except Exception as e:
                logger.warning(f"RemoteAgent {self.name} A2A failed, falling back to chat: {e}")

        return await self._send_chat_completion(messages)

    async def _send_a2a_message(self, text: str) -> str:
        """Send message via A2A SendMessage."""
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        inject(headers)
        response = await self._client.post(
            f"{self.card_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": text}],
                        "metadata": {"delegation": True},
                    },
                },
            },
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise RuntimeError(f"A2A error: {data['error'].get('message', 'unknown')}")

        result = data.get("result", {})
        artifacts = result.get("artifacts", [])
        for artifact in artifacts:
            for part in artifact.get("parts", []):
                if part.get("type") == "text":
                    return part["text"]

        output = result.get("output", "")
        if output:
            return output

        # Extract from history (last agent message)
        history = result.get("history", [])
        for msg in reversed(history):
            if msg.get("role") == "agent":
                parts = msg.get("parts", [])
                for part in parts:
                    if part.get("type") == "text" and part.get("text"):
                        return part["text"]

        fallback = result.get("status", {}).get("message", "")
        if not fallback:
            logger.warning(f"A2A response from {self.name} had no extractable text content")
        return fallback

    async def _send_chat_completion(self, messages: List[Dict[str, str]]) -> str:
        """Send message via OpenAI-compatible chat completions endpoint."""
        try:
            headers: Dict[str, str] = {}
            inject(headers)
            response = await self._client.post(
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
            await self._client.aclose()
        except Exception:
            pass


def _build_mock_model_function():
    """Build a FunctionModel handler from DEBUG_MOCK_RESPONSES. Returns (handler, state)."""
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


def _resolve_model(
    name: str,
    *,
    model: Any = None,
    model_api_url: Optional[str] = None,
    model_name: Optional[str] = None,
    tool_call_mode: str = "auto",
) -> tuple:
    """Resolve the Pydantic AI model from configuration. Returns (model, mock_state)."""
    if model is not None:
        return model, None

    mock_handler, mock_state = _build_mock_model_function()
    if mock_handler:
        logger.info(f"Agent {name}: using mock model (DEBUG_MOCK_RESPONSES)")
        return FunctionModel(mock_handler), mock_state

    if model_api_url and model_name:
        base_url = model_api_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        if tool_call_mode == "string":
            from pais.tools import build_string_mode_handler

            handler = build_string_mode_handler(base_url, model_name)
            logger.info(f"Agent {name}: using string-mode model {model_name} at {base_url}")
            return FunctionModel(handler, model_name=f"string:{model_name}"), None
        else:
            provider = OpenAIProvider(base_url=base_url, api_key="not-needed")
            logger.info(f"Agent {name}: using OpenAI model {model_name} at {base_url}")
            return OpenAIChatModel(model_name=model_name, provider=provider), None

    raise ValueError(
        "Agent requires either 'model', 'model_api_url'+'model_name', "
        "or DEBUG_MOCK_RESPONSES env var"
    )


def _extract_user_prompt(message: Union[str, List[Dict[str, str]]]) -> str:
    if isinstance(message, str):
        return message
    for msg in reversed(message):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _build_streaming_chunk(
    session_id: str,
    created_at: int,
    model_name: str,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> str:
    """Build an SSE data line for a streaming chat completion chunk."""
    delta = {"content": content} if content is not None else {}
    data = {
        "id": session_id,
        "object": "chat.completion.chunk",
        "created": created_at,
        "model": model_name,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(data)}\n\n"


def _build_chat_response(model_name: str, content: str, *, session_id: str) -> dict:
    """Build OpenAI-compatible non-streaming chat completion response dict."""
    return {
        "id": session_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class AgentServerSettings(BaseSettings):
    """Agent server configuration from environment variables."""

    # Required settings
    agent_name: str
    model_api_url: str = ""
    model_name: str = ""

    # Optional settings with defaults
    agent_description: str = "AI Agent"
    agent_instructions: str = "You are a helpful assistant."
    agent_system_prompt: str = ""
    agent_port: int = 8000
    agent_log_level: str = "INFO"

    # Sub-agent configuration (comma-separated list of name:url pairs)
    agent_sub_agents: str = ""

    # Kubernetes operator format (PEER_AGENTS comma-separated names)
    peer_agents: str = ""

    # MCP server configuration
    mcp_servers: str = ""

    # Agentic loop configuration
    agentic_loop_max_steps: int = 5

    # Tool calling mode: "auto" (default), "native", "string"
    tool_call_mode: str = "auto"

    # Memory configuration
    memory_enabled: bool = True
    memory_context_limit: int = 6
    memory_max_sessions: int = 1000
    memory_max_session_events: int = 500
    # Central memory service (long-term tier). When a MemoryStore is bound the
    # operator injects its endpoint here and the runtime uses the RemoteMemory
    # backend; when empty the runtime falls back to the in-process short-term
    # LocalMemory backend (no long-term tier, pod-local).
    memory_store_endpoint: str = ""
    memory_scope: str = "session"
    # Additive explicit memory tools exposed to the agent on top of the automatic
    # recall-inject/write-extract baseline: "all" (save + search), "read" (search
    # only), "write" (save only), or empty (none). Long-term tools require a bound
    # MemoryStore; the operator rejects a tools setting without one.
    memory_tools: str = ""
    # Empty means "inherit the memory store's configured default_failure_mode"; the
    # runtime only sends an explicit failure mode (soft|strict) when set here, so the
    # MemoryStore CRD default governs the runtime write/forget path by default.
    memory_failure_mode: str = ""
    memory_short_term_token_budget: int = 0
    memory_rolling_summary: bool = True
    # The agent's stable identity used as the owner of private/agent-scoped memory.
    agent_identity: str = ""

    # Task store configuration
    task_store_type: str = "local"

    # Autonomous execution settings (CRD mode — goal presence activates)
    autonomous_goal: str = ""
    autonomous_interval_seconds: int = 0
    autonomous_max_iter_runtime_seconds: int = 60

    # Task budget settings (A2A async task defaults)
    task_max_iterations: int = 10
    task_max_runtime_seconds: int = 300
    task_max_tool_calls: int = 50

    # Logging settings
    agent_access_log: bool = False

    # Agent identity propagation (dummy/static unless managed credentials are configured).
    # security_actor defaults to kaos://agent/{agent_name} when unset.
    security_actor: str = ""
    security_actor_token: str = ""
    security_principal: str = ""

    # Pydantic AI OTEL instrumentation settings
    otel_instrumentation_version: int = 5

    model_config = {"env_file": ".env", "case_sensitive": False}
