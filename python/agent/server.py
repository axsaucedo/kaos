"""
AgentServer implementation for OpenAI-compatible API.

FastAPI server with health probes, agent discovery, and chat completions endpoint.
Supports both streaming and non-streaming responses.
"""

import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings
import uvicorn

from modelapi.client import ModelAPI
from agent.client import Agent, RemoteAgent
from agent.memory import LocalMemory

logger = logging.getLogger(__name__)


class AgentServerSettings(BaseSettings):
    """Agent server configuration from environment variables."""

    # Required settings
    agent_name: str
    model_api_url: str
    model_name: str = "smollm2:135m"  # Default model

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

    # Agentic loop configuration (from K8s operator)
    agentic_loop_max_steps: int = 5

    # Debug settings (only enable in development/testing)
    agent_debug_memory_endpoints: bool = False

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
        debug_memory_endpoints: bool = False,
        access_log: bool = False,
    ):
        """Initialize AgentServer with an agent.

        Args:
            agent: Agent instance to serve
            port: Port to serve on
            debug_memory_endpoints: Whether to enable /memory/* endpoints (for testing)
            access_log: Whether to enable uvicorn access logs (default: False)
        """
        self.agent = agent
        self.port = port
        self.debug_memory_endpoints = debug_memory_endpoints
        self.access_log = access_log

        # Create FastAPI app
        self.app = FastAPI(
            title=f"Agent: {agent.name}",
            description=agent.description,
            lifespan=self._lifespan,
        )

        self._setup_routes()
        logger.info(f"AgentServer initialized for {agent.name} on port {port}")

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Manage agent lifecycle."""
        logger.info("AgentServer startup")
        yield
        logger.info("AgentServer shutdown")
        await self.agent.close()

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
            card = self.agent.get_agent_card(base_url)
            return JSONResponse(card.to_dict())

        # Debug memory endpoints (only enabled when debug_memory_endpoints=True)
        if self.debug_memory_endpoints:

            @self.app.get("/memory/events")
            async def get_memory_events():
                """Get all memory events for debugging/testing."""
                sessions = await self.agent.memory.list_sessions()
                all_events = []
                for sid in sessions:
                    events = await self.agent.memory.get_session_events(sid)
                    all_events.extend([e.to_dict() for e in events])
                return JSONResponse(
                    {
                        "agent": self.agent.name,
                        "events": all_events,
                        "total": len(all_events),
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
    """Create an AgentServer with optional sub-agents.

    Args:
        settings: Server settings (loaded from env if not provided)
        sub_agents: List of RemoteAgent instances (overrides settings.agent_sub_agents)

    Returns:
        AgentServer instance
    """
    import os

    if not settings:
        # Load from environment variables - requires AGENT_NAME and MODEL_API_URL
        settings = AgentServerSettings()  # type: ignore[call-arg]

    model_api = ModelAPI(model=settings.model_name, api_base=settings.model_api_url)

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

    # Create agentic loop config from settings
    from agent.client import AgenticLoopConfig

    loop_config = AgenticLoopConfig(max_steps=settings.agentic_loop_max_steps)

    agent = Agent(
        name=settings.agent_name,
        description=settings.agent_description,
        instructions=settings.agent_instructions,
        model_api=model_api,
        sub_agents=sub_agents,
        loop_config=loop_config,
    )

    server = AgentServer(
        agent,
        port=settings.agent_port,
        debug_memory_endpoints=settings.agent_debug_memory_endpoints,
        access_log=settings.agent_access_log,
    )

    logger.info(
        f"Created agent server: {settings.agent_name} with {len(sub_agents)} sub-agents, loop_config={loop_config}"
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
