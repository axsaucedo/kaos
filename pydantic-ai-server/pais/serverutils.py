"""Data classes, settings, and model resolution for KAOS agent framework."""

import os
import json
import time
import logging
from typing import Dict, Any, List, Literal, Optional, Union, TYPE_CHECKING
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
    from pais.memory import Memory

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    """Per-run dependencies passed via RunContext to tools."""

    session_id: str = ""
    memory: Optional["Memory"] = None


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
            self._active = True
            logger.info(f"RemoteAgent {self.name} active: {self.agent_card.description}")
            return True
        except Exception as e:
            self._active = False
            logger.warning(f"RemoteAgent {self.name} init failed: {type(e).__name__}: {e}")
            return False

    async def process_message(self, messages: List[Dict[str, str]]) -> str:
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")

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
        role = msg.get("role", "user")
        if role in ("user", "task-delegation"):
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
    memory_type: str = "local"
    memory_context_limit: int = 6
    memory_max_sessions: int = 1000
    memory_max_session_events: int = 500
    memory_redis_url: str = ""

    # Logging settings
    agent_access_log: bool = False

    # Pydantic AI OTEL instrumentation settings
    otel_instrumentation_version: int = 4
    otel_event_mode: Literal["attributes", "logs"] = "attributes"

    model_config = {"env_file": ".env", "case_sensitive": False}
