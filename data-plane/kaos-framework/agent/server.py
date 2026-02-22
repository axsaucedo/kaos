"""
AgentServer implementation for OpenAI-compatible API.

FastAPI server with health probes, agent discovery, and chat completions endpoint.
Supports both streaming and non-streaming responses.
Includes OpenTelemetry instrumentation for tracing, metrics, and log correlation.
Uses Pydantic AI as the core agent framework.
"""

import os
import time
import uuid
import json
import logging
import sys
from typing import Dict, Any, List, Literal, Optional, Union, TYPE_CHECKING
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic_settings import BaseSettings
from opentelemetry import trace as trace_api
import httpx
import uvicorn

from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse as PydanticModelResponse,
    TextPart,
    ToolCallPart,
)
from telemetry.manager import (
    init_otel,
    is_otel_enabled,
    should_enable_otel,
    get_log_level,
    getenv_bool,
    extract_trace_context,
    get_tracer,
    inject_trace_context,
)

if TYPE_CHECKING:
    from agent.memory import Memory


def configure_logging(level: str = "INFO", otel_correlation: bool = False) -> None:
    """Configure logging for the application.

    Sets up a consistent logging format and ensures all application loggers
    are properly configured to output to stdout.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        otel_correlation: If True, include trace_id and span_id in log format
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Log format with optional OTel correlation
    if otel_correlation:
        log_format = (
            "%(asctime)s - %(name)s - %(levelname)s - "
            "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] - %(message)s"
        )
    else:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # Override any existing configuration
    )

    # If OTel correlation is enabled, add the LoggingInstrumentor
    if otel_correlation:
        try:
            from opentelemetry.instrumentation.logging import LoggingInstrumentor

            LoggingInstrumentor().instrument(set_logging_format=False)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to enable OTel log correlation: {e}")

    # Ensure our application loggers are at the right level
    for logger_name in [
        "agent",
        "agent.server",
        "agent.client",
        "agent.memory",
    ]:
        logging.getLogger(logger_name).setLevel(log_level)

    # Reduce noise from third-party libraries
    # HTTPX/HTTPCORE: set to WARNING by default, or log_level if OTEL_INCLUDE_HTTP_CLIENT=true
    include_http_client = getenv_bool("OTEL_INCLUDE_HTTP_CLIENT", False)
    http_log_level = log_level if include_http_client else logging.WARNING
    logging.getLogger("httpx").setLevel(http_log_level)
    logging.getLogger("httpcore").setLevel(http_log_level)
    logging.getLogger("mcp.client.streamable_http").setLevel(http_log_level)

    # Uvicorn access logs: disabled by default, enable with OTEL_INCLUDE_HTTP_SERVER=true
    include_http_server = getenv_bool("OTEL_INCLUDE_HTTP_SERVER", False)
    logging.getLogger("uvicorn.error").setLevel(log_level)
    # Access logger at CRITICAL effectively disables it; at log_level enables it
    uvicorn_access_level = log_level if include_http_server else logging.CRITICAL
    logging.getLogger("uvicorn.access").setLevel(uvicorn_access_level)


logger = logging.getLogger(__name__)


# --- Classes moved from client.py ---


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


@dataclass
class AgentCard:
    """Agent discovery card for A2A protocol."""

    name: str
    description: str
    url: str
    skills: List[Dict[str, Any]]
    capabilities: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
            response = await self._client.get(f"{self.card_url}/.well-known/agent")
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
            inject_trace_context(headers)
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
    """Build a FunctionModel handler from DEBUG_MOCK_RESPONSES env var.

    Returns (handler, state) tuple where state is used to reset per-request.
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
    model: Any,
    model_api_url: Optional[str],
    model_name: Optional[str],
    tool_call_mode: str,
) -> tuple:
    """Resolve the Pydantic AI model from configuration.

    Returns (model, mock_state) tuple.
    """
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
            from agent.tools import build_string_mode_handler

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
    """Extract user prompt from string or message array."""
    if isinstance(message, str):
        return message
    for msg in reversed(message):
        role = msg.get("role", "user")
        if role in ("user", "task-delegation"):
            return msg.get("content", "")
    return ""


def _format_sse_chunk(chat_id: str, created_at: int, model_name: str, content: str) -> str:
    """Format a content chunk as an SSE data line."""
    data = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created_at,
        "model": model_name,
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }
    return f"data: {json.dumps(data)}\n\n"


class AgentServerSettings(BaseSettings):
    """Agent server configuration from environment variables."""

    # Required settings
    agent_name: str
    model_api_url: str
    model_name: str  # Required - no default, must be provided

    # Optional settings with defaults
    agent_description: str = "AI Agent"
    agent_instructions: str = "You are a helpful assistant."
    agent_port: int = 8000
    agent_log_level: str = "INFO"

    # Sub-agent configuration (comma-separated list of name:url pairs)
    # Format: "worker-1:http://localhost:8001,worker-2:http://localhost:8002"
    agent_sub_agents: str = ""

    # Alternative: Kubernetes operator format (PEER_AGENTS comma-separated names)
    # Individual URLs via PEER_AGENT_<NAME>_CARD_URL env vars
    peer_agents: str = ""

    # MCP server configuration (Kubernetes operator format)
    # Format: "[server1,server2]" or "server1,server2"
    # Individual URLs via MCP_SERVER_<NAME>_URL env vars
    mcp_servers: str = ""

    # Agentic loop configuration (from K8s operator)
    agentic_loop_max_steps: int = 5

    # Tool calling mode: "auto" (default), "native", "string"
    tool_call_mode: str = "auto"

    # Memory configuration
    memory_enabled: bool = True  # Enable/disable memory (NullMemory when disabled)
    memory_type: str = "local"  # Memory type: "local" or "redis"
    memory_context_limit: int = 6  # Messages to include in delegation context
    memory_max_sessions: int = 1000  # Maximum sessions to keep
    memory_max_session_events: int = 500  # Maximum events per session
    memory_redis_url: str = ""  # Redis URL (required when memory_type is "redis")

    # Logging settings
    agent_access_log: bool = False  # Mute uvicorn access logs by default

    # Pydantic AI OTEL instrumentation settings
    otel_instrumentation_version: int = 4  # 1-4 (v4 = latest with multimodal)
    otel_event_mode: Literal["attributes", "logs"] = "attributes"

    model_config = {"env_file": ".env", "case_sensitive": False}


class AgentServer:
    """AgentServer exposing OpenAI-compatible chat completions API."""

    def __init__(
        self,
        agent: Any,
        port: int = 8000,
        access_log: bool = False,
        settings: Optional["AgentServerSettings"] = None,
    ):
        """Initialize AgentServer with an agent.

        Args:
            agent: Agent instance to serve
            port: Port to serve on
            access_log: Whether to enable uvicorn access logs (default: False)
            settings: Optional settings for DEBUG-level config dump
        """
        self.agent = agent
        self.port = port
        self.access_log = access_log
        self._settings = settings

        # Create FastAPI app
        self.app = FastAPI(
            title=f"Agent: {agent.name}",
            description=agent.description,
            lifespan=self._lifespan,
        )

        self._setup_routes()
        self._setup_telemetry()
        logger.info(f"AgentServer initialized for {agent.name} on port {port}")

    def _setup_telemetry(self):
        """Setup OpenTelemetry instrumentation for FastAPI.

        HTTP server/client tracing is disabled by default to reduce noise.
        Enable with OTEL_INCLUDE_HTTP_SERVER=true (FastAPI) or OTEL_INCLUDE_HTTP_CLIENT=true (HTTPX).
        """
        if is_otel_enabled():
            try:
                # FastAPI instrumentation is opt-in (noisy with health probes)
                include_http_server = getenv_bool("OTEL_INCLUDE_HTTP_SERVER", False)

                # HTTPX instrumentation is opt-in (noisy with MCP SSE)
                include_http_client = getenv_bool("OTEL_INCLUDE_HTTP_CLIENT", False)

                instrumentations = []
                if include_http_server:
                    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                    FastAPIInstrumentor.instrument_app(self.app)
                    instrumentations.append("FastAPI")

                if include_http_client:
                    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

                    HTTPXClientInstrumentor().instrument()
                    instrumentations.append("HTTPX")

                if instrumentations:
                    logger.info(
                        f"OpenTelemetry HTTP instrumentation enabled: {', '.join(instrumentations)}"
                    )
                else:
                    logger.info("OpenTelemetry enabled (HTTP instrumentation disabled by default)")
            except Exception as e:
                logger.warning(f"Failed to enable OpenTelemetry instrumentation: {e}")

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Manage agent lifecycle."""
        self._log_startup_config(self._settings)
        yield
        logger.info("AgentServer shutdown")
        await self.agent.close()

    def _log_startup_config(self, settings: Optional["AgentServerSettings"] = None):
        """Log server configuration on startup for debugging.

        INFO level: compact summary of agent, model, tools, sub-agents, memory, otel.
        DEBUG level: full settings dump and detailed tool/sub-agent info.
        """
        sub_agents = list(self.agent.sub_agents.keys()) if self.agent.sub_agents else []
        mcp_count = len(self.agent._mcp_servers)

        # --- INFO: compact summary ---
        logger.info(
            f"AgentServer starting: name={self.agent.name} port={self.port} "
            f"model={self.agent._model} memory={type(self.agent.memory).__name__} "
            f"max_steps={self.agent.max_steps} mcp_servers={mcp_count} "
            f"sub_agents={sub_agents}"
        )

        otel_status = "disabled"
        if is_otel_enabled():
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "N/A")
            otel_status = f"enabled (endpoint={endpoint})"
        logger.info(f"OpenTelemetry: {otel_status}")

        # --- DEBUG: detailed startup info ---
        if logger.isEnabledFor(logging.DEBUG):
            if settings:
                logger.debug(f"AgentServerSettings: {settings.model_dump()}")
            for name, sa in (self.agent.sub_agents or {}).items():
                status = "active" if sa._active else "inactive"
                desc = sa.agent_card.description if sa.agent_card else "N/A"
                logger.debug(f"  sub-agent: {name} [{status}] {desc}")
            for i, mcp in enumerate(self.agent._mcp_servers):
                logger.debug(f"  mcp-server[{i}]: {mcp}")
            logger.debug(f"  access_log={self.access_log}")

    def _setup_routes(self):
        """Setup HTTP routes for health, A2A, and OpenAI endpoints."""

        @self.app.get("/health")
        async def health():
            """Health check endpoint for Kubernetes liveness probes."""
            return JSONResponse(
                {
                    "status": "healthy",
                    "name": self.agent.name,
                    "timestamp": int(time.time()),
                }
            )

        @self.app.get("/ready")
        async def ready():
            """Readiness check endpoint for Kubernetes readiness probes."""
            return JSONResponse(
                {
                    "status": "ready",
                    "name": self.agent.name,
                    "timestamp": int(time.time()),
                }
            )

        @self.app.get("/.well-known/agent")
        async def agent_card():
            """A2A agent discovery endpoint."""
            base_url = f"http://localhost:{self.port}"
            card = await self.agent.get_agent_card(base_url)
            return JSONResponse(card.to_dict())

        # Memory endpoints (always enabled - used by UI and debugging)
        @self.app.get("/memory/events")
        async def get_memory_events(
            limit: int = 100,
            session_id: Optional[str] = None,
        ):
            """Get memory events with optional filtering.

            Args:
                limit: Maximum number of events to return (default: 100, max: 1000)
                session_id: Filter to specific session (optional)
            """
            limit = min(limit, 1000)  # Cap at 1000

            if session_id:
                events = await self.agent.memory.get_session_events(session_id)
            else:
                sessions = await self.agent.memory.list_sessions()
                events = []
                for sid in sessions:
                    sid_events = await self.agent.memory.get_session_events(sid)
                    events.extend(sid_events)

            # Get most recent events up to limit
            events = events[-limit:] if len(events) > limit else events

            return JSONResponse(
                {
                    "agent": self.agent.name,
                    "events": [e.to_dict() for e in events],
                    "total": len(events),
                }
            )

        @self.app.get("/memory/sessions")
        async def get_memory_sessions():
            """Get list of memory sessions."""
            sessions = await self.agent.memory.list_sessions()
            return JSONResponse(
                {
                    "agent": self.agent.name,
                    "sessions": sessions,
                    "total": len(sessions),
                }
            )

        @self.app.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            """OpenAI-compatible chat completions endpoint (streaming + non-streaming).

            The agent decides when to delegate or call tools based on model response.
            Server only routes requests to the agent for processing.
            Extracts trace context from incoming headers for distributed tracing.

            Session ID can be provided via:
            - X-Session-ID header
            - session_id field in request body
            """
            try:
                body = await request.json()

                messages = body.get("messages", [])
                if not messages:
                    raise HTTPException(status_code=400, detail="messages are required")

                model_name = body.get("model", "agent")
                stream_requested = body.get("stream", False)

                # Extract session_id from header (preferred) or body
                session_id = request.headers.get("X-Session-ID") or body.get("session_id")

                # Validate at least one user or task-delegation message exists
                has_valid_message = any(
                    msg.get("role") in ["user", "task-delegation"] for msg in messages
                )
                if not has_valid_message:
                    raise HTTPException(
                        status_code=400,
                        detail="No user or task-delegation message found",
                    )

                # Extract parent trace context for distributed tracing
                # Span is created inside each method so it stays active during processing
                parent_ctx = extract_trace_context(request.headers)

                if stream_requested:
                    return await self._stream_chat_completion(
                        messages, model_name, session_id, parent_ctx
                    )
                else:
                    return await self._complete_chat_completion(
                        messages, model_name, session_id, parent_ctx
                    )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Chat completion error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

    def _build_span_attrs(self, session_id: Optional[str] = None) -> dict:
        """Build span attributes for server-run tracing."""
        attrs: dict = {"agent.name": self.agent.name}
        if session_id:
            attrs["session.id"] = session_id
        return attrs

    async def _complete_chat_completion(
        self,
        messages: list,
        model_name: str,
        session_id: Optional[str] = None,
        parent_ctx: Optional[Any] = None,
    ) -> JSONResponse:
        """Handle non-streaming chat completion."""
        tracer = get_tracer()

        with tracer.start_as_current_span(
            "server-run",
            context=parent_ctx,
            kind=trace_api.SpanKind.SERVER,
            attributes=self._build_span_attrs(session_id),
        ):
            response_content = ""
            async for chunk in self.agent.process_message(
                messages, stream=False, session_id=session_id
            ):
                response_content += chunk

            return JSONResponse(
                {
                    "id": f"chatcmpl-{uuid.uuid4().hex}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": response_content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }
            )

    async def _stream_chat_completion(
        self,
        messages: list,
        model_name: str,
        session_id: Optional[str] = None,
        parent_ctx: Optional[Any] = None,
    ) -> StreamingResponse:
        """Handle streaming chat completion with SSE."""
        span_attrs = self._build_span_attrs(session_id)

        async def generate_stream():
            # Span is created inside the generator so it stays active
            # for the entire duration (not closed before FastAPI consumes it)
            tracer = get_tracer()

            with tracer.start_as_current_span(
                "server-run",
                context=parent_ctx,
                kind=trace_api.SpanKind.SERVER,
                attributes=span_attrs,
            ):
                try:
                    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
                    created_at = int(time.time())

                    async for chunk in self.agent.process_message(
                        messages, stream=True, session_id=session_id
                    ):
                        if chunk:
                            yield _format_sse_chunk(chat_id, created_at, model_name, chunk)

                    # Final stop chunk
                    final_data = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_at,
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    yield f"data: {json.dumps(final_data)}\n\n"
                    yield "data: [DONE]\n\n"

                except Exception as e:
                    logger.error(f"Streaming error: {e}")
                    error_data = {"error": {"type": "server_error", "message": str(e)}}
                    yield f"data: {json.dumps(error_data)}\n\n"
                    yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    def run(self, host: str = "0.0.0.0"):
        """Run the server.

        Args:
            host: Host to bind to
        """
        logger.info(f"Starting AgentServer on {host}:{self.port}")
        uvicorn.run(self.app, host=host, port=self.port, access_log=self.access_log)


def create_agent_server(
    settings: Optional[AgentServerSettings] = None,
    sub_agents: Optional[List[RemoteAgent]] = None,
    custom_agent: Any = None,
) -> AgentServer:
    """Create an AgentServer with optional sub-agents and MCP clients.

    Args:
        settings: Server settings (loaded from env if not provided)
        sub_agents: List of RemoteAgent instances (overrides settings.agent_sub_agents)
        custom_agent: Pre-built Pydantic AI agent with custom tools (custom image pattern)

    Returns:
        AgentServer instance
    """
    if not settings:
        settings = AgentServerSettings()  # type: ignore[call-arg]

    # Check if OTel should be enabled based on env vars
    otel_should_enable = should_enable_otel()

    # Configure logging
    log_level = get_log_level()
    configure_logging(log_level, otel_correlation=otel_should_enable)

    # Parse MCP servers from settings -> Pydantic AI MCPServerStreamableHTTP
    mcp_servers: list = []
    if settings.mcp_servers:
        mcp_servers_str = settings.mcp_servers.strip()
        if mcp_servers_str.startswith("[") and mcp_servers_str.endswith("]"):
            mcp_servers_str = mcp_servers_str[1:-1]

        for server_name in mcp_servers_str.split(","):
            server_name = server_name.strip()
            if server_name:
                env_name = f"MCP_SERVER_{server_name}_URL"
                server_url = os.environ.get(env_name)
                if server_url:
                    # Append /mcp for Streamable HTTP MCP endpoint
                    mcp_url = server_url.rstrip("/")
                    if not mcp_url.endswith("/mcp"):
                        mcp_url = f"{mcp_url}/mcp"
                    mcp_servers.append(MCPServerStreamableHTTP(mcp_url))
                    logger.info(f"Configured MCP server: {server_name} -> {mcp_url}")
                else:
                    logger.warning(
                        f"No URL found for MCP server {server_name} (expected {env_name})"
                    )

    # Parse sub-agents from settings if not provided directly
    if sub_agents is None:
        sub_agents = []

        if settings.agent_sub_agents:
            for agent_spec in settings.agent_sub_agents.split(","):
                agent_spec = agent_spec.strip()
                if ":" in agent_spec:
                    name, url = agent_spec.split(":", 1)
                    sub_agents.append(RemoteAgent(name=name.strip(), card_url=url.strip()))
                    logger.info(f"Configured sub-agent (direct): {name} -> {url}")

        elif settings.peer_agents:
            for peer_name in settings.peer_agents.split(","):
                peer_name = peer_name.strip()
                if peer_name:
                    env_name = f"PEER_AGENT_{peer_name.upper().replace('-', '_')}_CARD_URL"
                    card_url = os.environ.get(env_name)
                    if card_url:
                        sub_agents.append(RemoteAgent(name=peer_name, card_url=card_url))
                        logger.info(f"Configured sub-agent (k8s): {peer_name} -> {card_url}")
                    else:
                        logger.warning(
                            f"No URL found for peer agent {peer_name} (expected {env_name})"
                        )

    # Create memory
    from agent.memory import LocalMemory, RedisMemory, NullMemory, Memory

    memory: Memory
    if settings.memory_enabled:
        if settings.memory_type == "redis" and settings.memory_redis_url:
            memory = RedisMemory(
                redis_url=settings.memory_redis_url,
                max_sessions=settings.memory_max_sessions,
                max_events_per_session=settings.memory_max_session_events,
            )
        else:
            if settings.memory_type == "redis":
                logger.warning("MEMORY_REDIS_URL not set, falling back to LocalMemory")
            memory = LocalMemory(
                max_sessions=settings.memory_max_sessions,
                max_events_per_session=settings.memory_max_session_events,
            )
    else:
        memory = NullMemory()

    # Initialize OpenTelemetry
    init_otel(settings.agent_name)

    # Enable Pydantic AI instrumentation with explicit KAOS OTEL providers
    if is_otel_enabled():
        from pydantic_ai.models.instrumented import InstrumentationSettings
        from opentelemetry.trace import get_tracer_provider
        from opentelemetry.metrics import get_meter_provider
        from opentelemetry._logs import get_logger_provider

        instrumentation = InstrumentationSettings(
            tracer_provider=get_tracer_provider(),
            meter_provider=get_meter_provider(),
            logger_provider=get_logger_provider(),
            version=settings.otel_instrumentation_version,  # type: ignore[arg-type]
            event_mode=settings.otel_event_mode,
        )
        PydanticAgent.instrument_all(instrumentation)

    # Lazy import to avoid circular dependency (temporary — removed in Task 5)
    from agent.client import Agent

    agent = Agent(
        name=settings.agent_name,
        description=settings.agent_description,
        instructions=settings.agent_instructions,
        model_api_url=settings.model_api_url,
        model_name=settings.model_name,
        mcp_servers=mcp_servers if mcp_servers else None,
        sub_agents=sub_agents,
        max_steps=settings.agentic_loop_max_steps,
        memory_context_limit=settings.memory_context_limit,
        memory=memory,
        tool_call_mode=settings.tool_call_mode,
        custom_pydantic_agent=custom_agent,
    )

    server = AgentServer(
        agent,
        port=settings.agent_port,
        access_log=settings.agent_access_log,
        settings=settings,
    )

    return server


def create_app(settings: Optional[AgentServerSettings] = None) -> FastAPI:
    """Create FastAPI app for uvicorn deployment."""
    server = create_agent_server(settings)
    logger.info("Created Agent FastAPI App")
    return server.app


def get_app() -> FastAPI:
    """Lazy app factory for uvicorn. Only creates app when called."""
    return create_app()


# For uvicorn: use "agent.server:get_app" with --factory flag
# Or use "agent.server:app" after setting required env vars
