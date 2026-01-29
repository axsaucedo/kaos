"""
AgentServer implementation for OpenAI-compatible API.

FastAPI server with health probes, agent discovery, and chat completions endpoint.
Supports both streaming and non-streaming responses.
Includes OpenTelemetry instrumentation for tracing, metrics, and log correlation.
"""

import os
import time
import uuid
import logging
import sys
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings
import uvicorn

from modelapi.client import ModelAPI
from agent.client import Agent, RemoteAgent
from agent.memory import LocalMemory
from mcptools.client import MCPClient
from telemetry.manager import init_otel, is_otel_enabled, should_enable_otel


def get_log_level() -> str:
    """Get log level from environment, preferring LOG_LEVEL over AGENT_LOG_LEVEL."""
    return os.getenv("LOG_LEVEL", os.getenv("AGENT_LOG_LEVEL", "INFO")).upper()


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
        "modelapi",
        "modelapi.client",
        "mcptools",
        "mcptools.client",
    ]:
        logging.getLogger(logger_name).setLevel(log_level)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(log_level)


logger = logging.getLogger(__name__)


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

    # Memory configuration
    memory_enabled: bool = True  # Enable/disable memory (NullMemory when disabled)
    memory_type: str = "local"  # Memory type (only "local" supported currently)
    memory_context_limit: int = 6  # Messages to include in delegation context
    memory_max_sessions: int = 1000  # Maximum sessions to keep
    memory_max_session_events: int = 500  # Maximum events per session

    # Logging settings
    agent_access_log: bool = False  # Mute uvicorn access logs by default

    class Config:
        env_file = ".env"
        case_sensitive = False


class ChatCompletionRequest(BaseModel):
    """OpenAI chat completion request model."""

    messages: List[Dict[str, str]]
    model: Optional[str] = None
    stream: Optional[bool] = False
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None


class AgentServer:
    """AgentServer exposing OpenAI-compatible chat completions API."""

    def __init__(
        self,
        agent: Agent,
        port: int = 8000,
        access_log: bool = False,
    ):
        """Initialize AgentServer with an agent.

        Args:
            agent: Agent instance to serve
            port: Port to serve on
            access_log: Whether to enable uvicorn access logs (default: False)
        """
        self.agent = agent
        self.port = port
        self.access_log = access_log

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
        """Setup OpenTelemetry instrumentation for FastAPI."""
        if is_otel_enabled():
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
                from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

                FastAPIInstrumentor.instrument_app(self.app)
                HTTPXClientInstrumentor().instrument()
                logger.info("OpenTelemetry instrumentation enabled (FastAPI + HTTPX)")
            except Exception as e:
                logger.warning(f"Failed to enable OpenTelemetry instrumentation: {e}")

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Manage agent lifecycle."""
        self._log_startup_config()
        yield
        logger.info("AgentServer shutdown")
        await self.agent.close()

    def _log_startup_config(self):
        """Log server configuration on startup for debugging."""
        logger.info("=" * 60)
        logger.info("AgentServer Starting")
        logger.info("=" * 60)
        logger.info(f"Agent Name: {self.agent.name}")
        logger.info(f"Description: {self.agent.description}")
        logger.info(f"Port: {self.port}")
        logger.info(f"Max Steps: {self.agent.max_steps}")
        logger.info(f"Memory Context Limit: {self.agent.memory_context_limit}")
        logger.info(f"Memory Enabled: {self.agent.memory_enabled}")
        logger.info(f"Log Level: {get_log_level()}")

        # Log model API info
        if self.agent.model_api:
            logger.info(f"Model API: {self.agent.model_api.api_base}")
            logger.info(f"Model: {self.agent.model_api.model}")

        # Log MCP tools
        if self.agent.mcp_clients:
            logger.info(f"MCP Servers: {len(self.agent.mcp_clients)}")
            for mcp in self.agent.mcp_clients:
                logger.info(f"  - {mcp.name}: {mcp.url}")
        else:
            logger.info("MCP Servers: None")

        # Log sub-agents
        if self.agent.sub_agents:
            logger.info(f"Sub-agents: {len(self.agent.sub_agents)}")
            for name, sub in self.agent.sub_agents.items():
                logger.info(f"  - {name}: {sub.card_url}")
        else:
            logger.info("Sub-agents: None")

        # Log OpenTelemetry configuration
        otel_enabled = is_otel_enabled()
        logger.info(f"OpenTelemetry Enabled: {otel_enabled}")
        if otel_enabled:
            logger.info(f"  OTEL_SERVICE_NAME: {os.getenv('OTEL_SERVICE_NAME', 'N/A')}")
            logger.info(
                f"  OTEL_EXPORTER_OTLP_ENDPOINT: {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'N/A')}"
            )
            logger.debug(
                f"  OTEL_RESOURCE_ATTRIBUTES: {os.getenv('OTEL_RESOURCE_ATTRIBUTES', 'N/A')}"
            )

        logger.info(f"Access Log: {self.access_log}")
        logger.info("=" * 60)

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
            """
            try:
                body = await request.json()

                messages = body.get("messages", [])
                if not messages:
                    raise HTTPException(status_code=400, detail="messages are required")

                model_name = body.get("model", "agent")
                stream_requested = body.get("stream", False)

                # Validate at least one user or task-delegation message exists
                has_valid_message = any(
                    msg.get("role") in ["user", "task-delegation"] for msg in messages
                )
                if not has_valid_message:
                    raise HTTPException(
                        status_code=400,
                        detail="No user or task-delegation message found",
                    )

                # Pass full messages array to agent for processing
                # Agent handles tool calls and delegations based on model response
                if stream_requested:
                    return await self._stream_chat_completion(messages, model_name)
                else:
                    return await self._complete_chat_completion(messages, model_name)

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Chat completion error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

    async def _complete_chat_completion(self, messages: list, model_name: str) -> JSONResponse:
        """Handle non-streaming chat completion.

        Args:
            messages: Full OpenAI-style messages array for context
            model_name: Model name for response
        """
        # Collect complete response
        response_content = ""
        async for chunk in self.agent.process_message(messages, stream=False):
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
                    "prompt_tokens": 0,  # Not counting for simplicity
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        )

    async def _stream_chat_completion(self, messages: list, model_name: str) -> StreamingResponse:
        """Handle streaming chat completion with SSE.

        Args:
            messages: Full OpenAI-style messages array for context
            model_name: Model name for response
        """

        async def generate_stream():
            """Generate SSE stream for OpenAI-compatible streaming."""
            try:
                chat_id = f"chatcmpl-{uuid.uuid4().hex}"
                created_at = int(time.time())

                # Stream response chunks
                async for chunk in self.agent.process_message(messages, stream=True):
                    if chunk:  # Only send non-empty chunks
                        sse_data = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_at,
                            "model": model_name,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk},
                                    "finish_reason": None,
                                }
                            ],
                        }

                        # Format as SSE
                        yield f"data: {str(sse_data).replace('None', 'null').replace(chr(39), chr(34))}\n\n"

                # Send final chunk to indicate completion
                final_data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created_at,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {str(final_data).replace('None', 'null').replace(chr(39), chr(34))}\n\n"
                yield "data: [DONE]\n\n"

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                error_data = {"error": {"type": "server_error", "message": str(e)}}
                yield f"data: {str(error_data).replace(chr(39), chr(34))}\n\n"
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
) -> AgentServer:
    """Create an AgentServer with optional sub-agents and MCP clients.

    Args:
        settings: Server settings (loaded from env if not provided)
        sub_agents: List of RemoteAgent instances (overrides settings.agent_sub_agents)

    Returns:
        AgentServer instance
    """
    import os
    import re

    if not settings:
        # Load from environment variables - requires AGENT_NAME and MODEL_API_URL
        settings = AgentServerSettings()  # type: ignore[call-arg]

    # Check if OTel should be enabled based on env vars (before init_otel)
    otel_should_enable = should_enable_otel()

    # Configure logging with optional OTel correlation
    # Use LOG_LEVEL env var (preferred) or fallback to AGENT_LOG_LEVEL
    log_level = get_log_level()
    configure_logging(log_level, otel_correlation=otel_should_enable)

    model_api = ModelAPI(model=settings.model_name, api_base=settings.model_api_url)

    # Parse MCP servers from settings
    # Format: "[server1,server2]" or "server1,server2"
    mcp_clients: List[MCPClient] = []
    if settings.mcp_servers:
        # Remove brackets if present (K8s operator format: "[name1,name2]")
        mcp_servers_str = settings.mcp_servers.strip()
        if mcp_servers_str.startswith("[") and mcp_servers_str.endswith("]"):
            mcp_servers_str = mcp_servers_str[1:-1]

        for server_name in mcp_servers_str.split(","):
            server_name = server_name.strip()
            if server_name:
                # Look for MCP_SERVER_<NAME>_URL env var
                # Operator uses exact name: MCP_SERVER_<name>_URL (preserves hyphens and case)
                env_name = f"MCP_SERVER_{server_name}_URL"
                server_url = os.environ.get(env_name)
                if server_url:
                    mcp_clients.append(MCPClient(name=server_name, url=server_url))
                    logger.info(f"Configured MCP server: {server_name} -> {server_url}")
                else:
                    logger.warning(
                        f"No URL found for MCP server {server_name} (expected {env_name})"
                    )

    # Parse sub-agents from settings if not provided directly
    if sub_agents is None:
        sub_agents = []

        # Method 1: Direct agent_sub_agents format "name:url,name:url"
        if settings.agent_sub_agents:
            for agent_spec in settings.agent_sub_agents.split(","):
                agent_spec = agent_spec.strip()
                if ":" in agent_spec:
                    name, url = agent_spec.split(":", 1)
                    sub_agents.append(RemoteAgent(name=name.strip(), card_url=url.strip()))
                    logger.info(f"Configured sub-agent (direct): {name} -> {url}")

        # Method 2: Kubernetes operator format with PEER_AGENTS and PEER_AGENT_<NAME>_CARD_URL
        elif settings.peer_agents:
            for peer_name in settings.peer_agents.split(","):
                peer_name = peer_name.strip()
                if peer_name:
                    # Look for PEER_AGENT_<NAME>_CARD_URL env var
                    env_name = f"PEER_AGENT_{peer_name.upper().replace('-', '_')}_CARD_URL"
                    card_url = os.environ.get(env_name)
                    if card_url:
                        sub_agents.append(RemoteAgent(name=peer_name, card_url=card_url))
                        logger.info(f"Configured sub-agent (k8s): {peer_name} -> {card_url}")
                    else:
                        logger.warning(
                            f"No URL found for peer agent {peer_name} (expected {env_name})"
                        )

    # Create agent with MCP clients and sub-agents
    # Use NullMemory when memory is disabled
    from agent.memory import LocalMemory, NullMemory

    if settings.memory_enabled:
        memory = LocalMemory(
            max_sessions=settings.memory_max_sessions,
            max_events_per_session=settings.memory_max_session_events,
        )
    else:
        memory = NullMemory()

    # Initialize OpenTelemetry if enabled (uses standard OTEL_* env vars)
    # Note: LoggingInstrumentor is already called in configure_logging() above
    init_otel(settings.agent_name)

    agent = Agent(
        name=settings.agent_name,
        description=settings.agent_description,
        instructions=settings.agent_instructions,
        model_api=model_api,
        mcp_clients=mcp_clients,
        sub_agents=sub_agents,
        max_steps=settings.agentic_loop_max_steps,
        memory_context_limit=settings.memory_context_limit,
        memory=memory,
        memory_enabled=settings.memory_enabled,
    )

    server = AgentServer(
        agent,
        port=settings.agent_port,
        access_log=settings.agent_access_log,
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
