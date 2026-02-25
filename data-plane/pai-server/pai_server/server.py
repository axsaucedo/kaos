"""AgentServer: FastAPI server with health probes, A2A discovery, and OpenAI-compatible chat completions."""

import os
import time
import json
import logging
import sys
from typing import Dict, Any, AsyncIterator, List, Optional, Union, TYPE_CHECKING
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace as trace_api
import uvicorn

from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.usage import UsageLimits
from pydantic_ai._agent_graph import CallToolsNode
from pydantic_graph import End
from pai_server.telemetry import (
    init_otel,
    is_otel_enabled,
    should_enable_otel,
    get_log_level,
    getenv_bool,
    SERVICE_NAME,
)
from opentelemetry.propagate import extract
from pai_server.tools import format_progress_event, DELEGATION_TOOL_PREFIX, DelegationToolset
from pai_server.serverutils import (
    AgentDeps,
    AgentCard,
    RemoteAgent,
    AgentServerSettings,
    _MockResponseState,
    _build_mock_model_function,
    _resolve_model,
    _extract_user_prompt,
    _build_streaming_chunk,
    _build_chat_response,
)

if TYPE_CHECKING:
    from pai_server.memory import Memory


def configure_logging(level: str = "INFO", otel_correlation: bool = False) -> None:
    """Configure stdout logging with optional OTel trace correlation."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    log_format = (
        "%(asctime)s - %(name)s - %(levelname)s - "
        "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] - %(message)s"
        if otel_correlation
        else "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    if otel_correlation:
        try:
            from opentelemetry.instrumentation.logging import LoggingInstrumentor

            LoggingInstrumentor().instrument(set_logging_format=False)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to enable OTel log correlation: {e}")

    # Suppress noisy third-party loggers
    include_http_client = getenv_bool("OTEL_INCLUDE_HTTP_CLIENT", False)
    http_log_level = log_level if include_http_client else logging.WARNING
    for name in ("httpx", "httpcore", "mcp.client.streamable_http"):
        logging.getLogger(name).setLevel(http_log_level)

    include_http_server = getenv_bool("OTEL_INCLUDE_HTTP_SERVER", False)
    logging.getLogger("uvicorn.error").setLevel(log_level)
    logging.getLogger("uvicorn.access").setLevel(
        log_level if include_http_server else logging.CRITICAL
    )


logger = logging.getLogger(__name__)


class AgentServer:
    """AgentServer exposing OpenAI-compatible chat completions API."""

    def __init__(
        self,
        pydantic_agent: PydanticAgent[AgentDeps],
        settings: "AgentServerSettings",
        memory: Optional["Memory"] = None,
        mock_state: Optional[_MockResponseState] = None,
        sub_agents: Optional[Dict[str, RemoteAgent]] = None,
        mcp_servers: Optional[list] = None,
        model: Any = None,
        custom_tools: Optional[list] = None,
    ):
        from pai_server.memory import NullMemory

        self.settings = settings
        self.memory: "Memory" = memory or NullMemory()
        self._agent = pydantic_agent
        self._mock_state = mock_state
        self._sub_agents = sub_agents or {}
        self._mcp_servers = mcp_servers or []
        self._model = model
        self._custom_tools = custom_tools or []

        self.app = FastAPI(
            title=f"Agent: {self.settings.agent_name}",
            description=self.settings.agent_description,
            lifespan=self._lifespan,
        )

        self._setup_routes()
        self._setup_telemetry()
        logger.info(
            f"AgentServer initialized for {self.settings.agent_name} on port {self.settings.agent_port}"
        )

    def _setup_telemetry(self):
        """Setup OTel HTTP instrumentation (opt-in to reduce noise)."""
        if not is_otel_enabled():
            return
        try:
            enabled = []
            if getenv_bool("OTEL_INCLUDE_HTTP_SERVER", False):
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                FastAPIInstrumentor.instrument_app(self.app)
                enabled.append("FastAPI")
            if getenv_bool("OTEL_INCLUDE_HTTP_CLIENT", False):
                from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

                HTTPXClientInstrumentor().instrument()
                enabled.append("HTTPX")
            logger.info(f"OTel HTTP instrumentation: {', '.join(enabled) or 'none (opt-in)'}")
        except Exception as e:
            logger.warning(f"Failed to enable OTel HTTP instrumentation: {e}")

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        self._log_startup_config()
        yield
        logger.info("AgentServer shutdown")
        for sub_agent in self._sub_agents.values():
            await sub_agent.close()
        # TODO: Close MCP server connections (MCPServerStreamableHTTP) on shutdown
        await self.memory.close()

    def _log_startup_config(self):
        """Log agent config at INFO (summary) and DEBUG (full dump)."""
        sub_agents = list(self._sub_agents.keys()) if self._sub_agents else []
        mcp_count = len(self._mcp_servers)
        otel = "enabled" if is_otel_enabled() else "disabled"
        logger.info(
            f"AgentServer starting: name={self.settings.agent_name} port={self.settings.agent_port} "
            f"model={self._model} memory={type(self.memory).__name__} "
            f"max_steps={self.settings.agentic_loop_max_steps} mcp_servers={mcp_count} "
            f"sub_agents={sub_agents} otel={otel} "
            f"custom_tools={len(self._custom_tools)}"
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"AgentServerSettings: {self.settings.model_dump()}")

    def _setup_routes(self):

        @self.app.get("/health")
        async def health():
            return self._probe_response("healthy")

        @self.app.get("/ready")
        async def ready():
            return self._probe_response("ready")

        @self.app.get("/.well-known/agent.json")
        async def agent_card():
            # TODO: Derive base_url from request.headers["host"] or make configurable
            base_url = f"http://localhost:{self.settings.agent_port}"
            card = await self._get_agent_card(base_url)
            return JSONResponse(card.to_dict())

        # Memory endpoints (always enabled - used by UI and debugging)
        @self.app.get("/memory/events")
        async def get_memory_events(
            limit: int = 100,
            session_id: Optional[str] = None,
        ):
            limit = min(limit, 1000)

            if session_id:
                events = await self.memory.get_session_events(session_id)
            else:
                sessions = await self.memory.list_sessions()
                events = []
                for sid in sessions:
                    sid_events = await self.memory.get_session_events(sid)
                    events.extend(sid_events)

            events = events[-limit:] if len(events) > limit else events

            return JSONResponse(
                {
                    "agent": self.settings.agent_name,
                    "events": [e.to_dict() for e in events],
                    "total": len(events),
                }
            )

        @self.app.get("/memory/sessions")
        async def get_memory_sessions():
            sessions = await self.memory.list_sessions()
            return JSONResponse(
                {
                    "agent": self.settings.agent_name,
                    "sessions": sessions,
                    "total": len(sessions),
                }
            )

        @self.app.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            """OpenAI-compatible chat completions (streaming + non-streaming).

            Session ID via X-Session-ID header or session_id body field.
            """
            try:
                body = await request.json()

                messages = body.get("messages", [])
                if not messages:
                    raise HTTPException(status_code=400, detail="messages are required")

                model_name = body.get("model", "agent")
                stream_requested = body.get("stream", False)

                # Resolve session: client-provided or auto-generated
                session_id = request.headers.get("X-Session-ID") or body.get("session_id")
                if session_id:
                    session_id = await self.memory.get_or_create_session(
                        session_id, "agent", "user"
                    )
                else:
                    session_id = await self.memory.create_session("agent", "user")

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
                parent_ctx = extract(dict(request.headers))

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

    def _probe_response(self, status: str) -> JSONResponse:
        return JSONResponse(
            {"status": status, "name": self.settings.agent_name, "timestamp": int(time.time())}
        )

    def _build_span_attrs(self, session_id: str) -> dict:
        return {"agent.name": self.settings.agent_name, "session.id": session_id}

    async def _get_agent_card(self, base_url: str) -> AgentCard:
        from pai_server import __version__
        from pai_server.serverutils import AgentCardSkill, AgentCardCapabilities

        skills: list[AgentCardSkill] = [
            AgentCardSkill(id=t["name"], **t) for t in self._custom_tools
        ]
        for mcp_server in self._mcp_servers:
            try:
                async with mcp_server:
                    tools = await mcp_server.list_tools()
                    skills.extend(
                        AgentCardSkill(id=t.name, name=t.name, description=t.description or "")
                        for t in tools
                    )
            except Exception as e:
                logger.warning(f"Failed to list tools from MCP server: {e}")

        skills.extend(
            AgentCardSkill(
                id=f"{DELEGATION_TOOL_PREFIX}{n}",
                name=f"{DELEGATION_TOOL_PREFIX}{n}",
                description=f"Delegate task to {n}",
            )
            for n in self._sub_agents
        )

        capabilities = AgentCardCapabilities(
            streaming=True,
            push_notifications=False,
            state_transition_history=False,
        )

        return AgentCard(
            name=self.settings.agent_name,
            description=self.settings.agent_description,
            url=base_url,
            version=__version__,
            skills=skills,
            capabilities=capabilities,
        )

    async def _prepare_run(
        self,
        message: Union[str, List[Dict[str, str]]],
        session_id: str,
    ) -> tuple:
        """Setup for agent run: memory event, history, deps. Returns (user_prompt, message_history, deps, usage_limits)."""
        if self._mock_state:
            self._mock_state.reset()

        # Ensure session exists in memory (idempotent)
        session_id = await self.memory.get_or_create_session(session_id, "agent", "user")

        user_prompt = _extract_user_prompt(message)
        is_delegation = isinstance(message, list) and any(
            msg.get("role") == "task-delegation" for msg in message
        )
        await self.memory.add_event(
            session_id, "task_delegation_received" if is_delegation else "user_message", user_prompt
        )

        message_history = await self.memory.build_message_history(
            session_id, self.settings.memory_context_limit
        )
        deps = AgentDeps(session_id=session_id, memory=self.memory)
        usage_limits = UsageLimits(request_limit=self.settings.agentic_loop_max_steps)
        return user_prompt, message_history, deps, usage_limits

    async def _process_message(
        self,
        message: Union[str, List[Dict[str, str]]],
        session_id: str,
        stream: bool = False,
    ) -> AsyncIterator[str]:
        """Yields content chunks (streaming) or single complete response."""
        user_prompt, message_history, deps, usage_limits = await self._prepare_run(
            message, session_id
        )
        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        try:
            if stream:
                full_response = ""
                step = 0
                async with self._agent.iter(
                    user_prompt,
                    message_history=message_history,
                    usage_limits=usage_limits,
                    deps=deps,
                ) as run:
                    node = run.next_node
                    while not isinstance(node, End):
                        if isinstance(node, CallToolsNode):
                            has_tools = any(
                                isinstance(p, ToolCallPart) for p in node.model_response.parts
                            )
                            if has_tools:
                                step += 1
                            for part in node.model_response.parts:
                                if isinstance(part, ToolCallPart):
                                    yield format_progress_event(
                                        part, step, self.settings.agentic_loop_max_steps
                                    )
                        node = await run.next(node)

                if run.result:
                    full_response = str(run.result.output)
                    yield full_response

                await self.memory.add_event(session_id, "agent_response", full_response)
                new_msgs = run.result.new_messages() if run.result else []
                for msg in new_msgs:
                    await self.memory.store_pydantic_message(session_id, msg)
            else:
                result = await self._agent.run(
                    user_prompt,
                    message_history=message_history,
                    usage_limits=usage_limits,
                    deps=deps,
                )
                content = str(result.output) if result.output else ""
                await self.memory.add_event(session_id, "agent_response", content)
                for msg in result.new_messages():
                    await self.memory.store_pydantic_message(session_id, msg)
                yield content

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            await self.memory.add_event(session_id, "error", str(e))
            yield f"Sorry, I encountered an error: {str(e)}"

    async def _complete_chat_completion(
        self,
        messages: list,
        model_name: str,
        session_id: str,
        parent_ctx: Optional[Any] = None,
    ) -> JSONResponse:
        tracer = trace_api.get_tracer(SERVICE_NAME)

        with tracer.start_as_current_span(
            "server-run",
            context=parent_ctx,
            kind=trace_api.SpanKind.SERVER,
            attributes=self._build_span_attrs(session_id),
        ):
            response_content = ""
            async for chunk in self._process_message(messages, stream=False, session_id=session_id):
                response_content += chunk

            return JSONResponse(
                _build_chat_response(model_name, response_content, session_id=session_id)
            )

    async def _stream_chat_completion(
        self,
        messages: list,
        model_name: str,
        session_id: str,
        parent_ctx: Optional[Any] = None,
    ) -> StreamingResponse:
        span_attrs = self._build_span_attrs(session_id)

        async def generate_stream():
            # Span is created inside the generator so it stays active
            # for the entire duration (not closed before FastAPI consumes it)
            tracer = trace_api.get_tracer(SERVICE_NAME)

            with tracer.start_as_current_span(
                "server-run",
                context=parent_ctx,
                kind=trace_api.SpanKind.SERVER,
                attributes=span_attrs,
            ):
                try:
                    created_at = int(time.time())

                    async for chunk in self._process_message(
                        messages, stream=True, session_id=session_id
                    ):
                        if chunk:
                            yield _build_streaming_chunk(
                                session_id, created_at, model_name, content=chunk
                            )

                    yield _build_streaming_chunk(
                        session_id, created_at, model_name, finish_reason="stop"
                    )
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
        logger.info(f"Starting AgentServer on {host}:{self.settings.agent_port}")
        uvicorn.run(
            self.app,
            host=host,
            port=self.settings.agent_port,
            access_log=self.settings.agent_access_log,
        )


def _parse_mcp_servers(settings: AgentServerSettings) -> list:
    """Parse MCP server env vars into MCPServerStreamableHTTP instances."""
    mcp_servers: list = []
    if not settings.mcp_servers:
        return mcp_servers

    mcp_servers_str = settings.mcp_servers.strip()
    if mcp_servers_str.startswith("[") and mcp_servers_str.endswith("]"):
        mcp_servers_str = mcp_servers_str[1:-1]

    for server_name in mcp_servers_str.split(","):
        server_name = server_name.strip()
        if not server_name:
            continue
        env_name = f"MCP_SERVER_{server_name}_URL"
        server_url = os.environ.get(env_name)
        if server_url:
            mcp_url = server_url.rstrip("/")
            if not mcp_url.endswith("/mcp"):
                mcp_url = f"{mcp_url}/mcp"
            mcp_servers.append(MCPServerStreamableHTTP(mcp_url))
            logger.info(f"Configured MCP server: {server_name} -> {mcp_url}")
        else:
            logger.warning(f"No URL found for MCP server {server_name} (expected {env_name})")
    return mcp_servers


def _parse_sub_agents(settings: AgentServerSettings) -> List[RemoteAgent]:
    """Parse sub-agent env vars into RemoteAgent instances."""
    sub_agents: List[RemoteAgent] = []

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
            if not peer_name:
                continue
            env_name = f"PEER_AGENT_{peer_name.upper().replace('-', '_')}_CARD_URL"
            card_url = os.environ.get(env_name)
            if card_url:
                sub_agents.append(RemoteAgent(name=peer_name, card_url=card_url))
                logger.info(f"Configured sub-agent (k8s): {peer_name} -> {card_url}")
            else:
                logger.warning(f"No URL found for peer agent {peer_name} (expected {env_name})")
    return sub_agents


def _create_memory(settings: AgentServerSettings) -> "Memory":
    """Create memory backend from settings."""
    from pai_server.memory import LocalMemory, RedisMemory, NullMemory

    if not settings.memory_enabled:
        return NullMemory()

    if settings.memory_type == "redis" and settings.memory_redis_url:
        return RedisMemory(
            redis_url=settings.memory_redis_url,
            max_sessions=settings.memory_max_sessions,
            max_events_per_session=settings.memory_max_session_events,
        )

    if settings.memory_type == "redis":
        logger.warning("MEMORY_REDIS_URL not set, falling back to LocalMemory")
    return LocalMemory(
        max_sessions=settings.memory_max_sessions,
        max_events_per_session=settings.memory_max_session_events,
    )


def _setup_otel_instrumentation(settings: AgentServerSettings) -> None:
    """Initialize OTel SDK and Pydantic AI instrumentation."""
    init_otel(settings.agent_name)

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


def create_agent_server(
    settings: Optional[AgentServerSettings] = None,
    sub_agents: Optional[List[RemoteAgent]] = None,
    custom_agent: Any = None,
) -> AgentServer:
    """Create an AgentServer with optional sub-agents and MCP clients."""
    if not settings:
        settings = AgentServerSettings()  # type: ignore[call-arg]

    # Logging + OTel
    configure_logging(get_log_level(), otel_correlation=should_enable_otel())
    _setup_otel_instrumentation(settings)

    # Parse env-var resources
    mcp_servers = _parse_mcp_servers(settings)
    if sub_agents is None:
        sub_agents = _parse_sub_agents(settings)
    memory = _create_memory(settings)

    sub_agents_dict: Dict[str, RemoteAgent] = {a.name: a for a in sub_agents}

    # Resolve model
    model, mock_state = _resolve_model(
        settings.agent_name,
        model_api_url=settings.model_api_url,
        model_name=settings.model_name,
        tool_call_mode=settings.tool_call_mode,
    )

    # Build toolsets
    toolsets: list = list(mcp_servers)
    if sub_agents_dict:
        toolsets.append(DelegationToolset(sub_agents_dict, settings.memory_context_limit))

    # Create or augment Pydantic AI agent
    custom_tools = []
    if custom_agent:
        pydantic_agent = custom_agent
        pydantic_agent.model = model
        for ts in toolsets:
            pydantic_agent._toolsets.append(ts)
        # Extract custom tool names from agent's existing toolsets (before KAOS additions)
        if hasattr(custom_agent, "_function_toolset"):
            ft = custom_agent._function_toolset
            if hasattr(ft, "tools") and isinstance(ft.tools, dict):
                for name, tool in ft.tools.items():
                    if not name.startswith(DELEGATION_TOOL_PREFIX):
                        custom_tools.append(
                            {"name": name, "description": getattr(tool, "description", "") or ""}
                        )
        logger.info(f"Agent {settings.agent_name}: using custom Pydantic AI agent")
    else:
        pydantic_agent = PydanticAgent(
            model=model,
            instructions=settings.agent_instructions,
            name=settings.agent_name,
            defer_model_check=True,
            deps_type=AgentDeps,
            toolsets=toolsets if toolsets else None,
        )

    logger.info(
        f"Agent initialized: {settings.agent_name} "
        f"(sub_agents={list(sub_agents_dict.keys())}, "
        f"mcp_servers={len(mcp_servers)}, "
        f"tool_call_mode={settings.tool_call_mode})"
    )

    return AgentServer(
        pydantic_agent=pydantic_agent,
        settings=settings,
        memory=memory,
        mock_state=mock_state,
        sub_agents=sub_agents_dict,
        mcp_servers=mcp_servers,
        model=model,
        custom_tools=custom_tools,
    )


def create_app(settings: Optional[AgentServerSettings] = None) -> FastAPI:
    server = create_agent_server(settings)
    logger.info("Created Agent FastAPI App")
    return server.app


def get_app() -> FastAPI:
    return create_app()


# For uvicorn: use "agent.server:get_app" with --factory flag
# Or use "agent.server:app" after setting required env vars
