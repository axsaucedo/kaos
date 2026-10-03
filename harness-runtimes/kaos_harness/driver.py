"""FastAPI app serving the KAOS Agent HTTP contract in front of a coding harness.

The operator never talks to the process inside an agent pod — it resolves
dependencies into env vars and talks HTTP to ``:8000``. So a pod that serves the
same routes ``pydantic-ai-server`` serves is indistinguishable from a pydantic-ai
agent to the operator, ``kaos-cli`` and ``kaos-ui``, and needs no new CRD.

Routes, and who depends on each:

===============================  ==========================================
``GET  /health``                 operator liveness probe
``GET  /ready``                  operator readiness probe
``GET  /.well-known/agent.json`` A2A card; ``RemoteAgent`` branches on
                                 ``supportedProtocols`` containing ``jsonrpc``
``GET  /tools``                  tool listing
``GET  /memory/events``          kaos-ui memory tab (2s poll)
``GET  /memory/sessions``        session listing
``POST /v1/chat/completions``    kaos-cli + kaos-ui chat, SSE when ``stream``
``POST /``                       A2A JSON-RPC
===============================  ==========================================

``GET /sessions`` is a driver extra, not part of the contract: it exposes the
per-session workspace mapping that has no home on ``AgentStatus``.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .harnesses import HarnessConfig, get_harness

# Progress events carry a step budget so clients can render a bar. The harness
# owns its own loop and never exposes one, so this is a display bound only.
MAX_STEPS = 25

_SAFE_SESSION = re.compile(r"[^A-Za-z0-9._-]")


class Settings:
    """Driver configuration. Env vars only — the operator supplies all of them."""

    def __init__(self) -> None:
        self.agent_name = os.environ.get("AGENT_NAME", "harness")
        self.agent_description = os.environ.get("AGENT_DESCRIPTION", "coding harness agent")
        self.agent_instructions = os.environ.get("AGENT_INSTRUCTIONS", "")
        self.agent_port = int(os.environ.get("AGENT_PORT", "8000"))
        self.model_api_url = os.environ.get("MODEL_API_URL", "")
        self.model_name = os.environ.get("MODEL_NAME", "mock-model")
        self.harness_driver = os.environ.get("HARNESS_DRIVER", "pi")
        self.workspace = os.environ.get("HARNESS_WORKSPACE", "/workspace")
        self.state_dir = os.environ.get("HARNESS_STATE_DIR", "/state")
        self.harness_bin = os.environ.get("HARNESS_BIN", "")
        self.api_key = os.environ.get("MODEL_API_KEY", "not-needed")
        self.timeout_seconds = float(os.environ.get("HARNESS_TIMEOUT_SECONDS", "600"))

    def harness_config(self) -> HarnessConfig:
        return HarnessConfig(
            model_api_url=self.model_api_url,
            model_name=self.model_name,
            instructions=self.agent_instructions,
            state_dir=self.state_dir,
            binary=self.harness_bin,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class DriverState:
    """In-process session, event and task state.

    Mirrors ``LocalMemory``/``LocalTaskManager`` semantics closely enough for the
    UI and CLI; the harness keeps its own durable transcript under the state dir.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.harness = get_harness(settings.harness_driver, settings.harness_config())
        self.events: Dict[str, List[Dict[str, Any]]] = {}
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.workspaces: Dict[str, str] = {}

    # --- memory ------------------------------------------------------------

    def record(self, session_id: str, event_type: str, content: Any, **metadata: Any) -> None:
        self.events.setdefault(session_id, []).append(
            {
                "event_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "content": content,
                "metadata": {"session_id": session_id, **metadata},
            }
        )

    # --- workspaces --------------------------------------------------------

    def session_workspace(self, session_id: str) -> str:
        """Give every session its own directory so one pod serves N sessions.

        An Agent is always one pod (``replicas`` is a literal in the operator),
        but a pod is not one session: sessions are keyed off ``X-Session-ID`` and
        routed by header, not by Service endpoint. What that costs is isolation
        and per-session resource limits, not concurrency.
        """
        root = self.settings.workspace
        if not os.path.isdir(root):
            return ""
        safe = _SAFE_SESSION.sub("_", session_id) or "default"
        workspace = os.path.join(root, ".sessions", safe)
        os.makedirs(workspace, exist_ok=True)
        self.workspaces[session_id] = workspace
        return workspace

    # --- harness -----------------------------------------------------------

    async def run(self, prompt: str, session_id: str) -> AsyncIterator[Tuple[str, Any]]:
        """Drive one harness turn, yielding ``(kind, payload)`` as it goes.

        ``kind`` is ``progress`` (a dict to be JSON-encoded into ``delta.content``)
        or ``text`` (assistant output).
        """
        workspace = self.session_workspace(session_id)
        self.record(session_id, "user_message", prompt)
        step = 0
        async for event in self.harness.run(prompt, session_id, workspace):
            if event.kind == "tool_call":
                step += 1
                self.record(session_id, "tool_call", event.target, step=step)
                yield (
                    "progress",
                    {
                        "type": "progress",
                        "step": step,
                        "max_steps": MAX_STEPS,
                        "action": "tool_call",
                        "target": event.target,
                    },
                )
            elif event.kind == "usage":
                self.record(session_id, "usage", event.usage)
            elif event.kind == "text":
                self.record(session_id, "agent_response", event.text)
                yield ("text", event.text)

    async def collect(self, prompt: str, session_id: str) -> str:
        parts = [payload async for kind, payload in self.run(prompt, session_id) if kind == "text"]
        return "\n".join(parts)


def _chunk(
    state: DriverState, session_id: str, content: Optional[str], finish: Optional[str] = None
) -> Dict[str, Any]:
    """One SSE chunk in the exact shape kaos-cli and kaos-ui already parse."""
    return {
        "id": session_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": state.settings.model_name,
        "choices": [
            {
                "index": 0,
                "delta": ({"content": content} if content is not None else {}),
                "finish_reason": finish,
            }
        ],
    }


def _session_id(request: Request, body: Dict[str, Any]) -> str:
    return request.headers.get("X-Session-ID") or body.get("session_id") or str(uuid.uuid4())


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings()
    state = DriverState(settings)
    state.harness.prepare()

    app = FastAPI(title=f"kaos-harness/{settings.agent_name}")
    app.state.driver = state

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "healthy", "agent": settings.agent_name}

    @app.get("/ready")
    async def ready() -> Dict[str, Any]:
        return {
            "status": "ready",
            "agent": settings.agent_name,
            "harness": state.harness.name,
            "available": state.harness.available(),
        }

    @app.get("/.well-known/agent.json")
    async def agent_card() -> Dict[str, Any]:
        return {
            "name": settings.agent_name,
            "description": settings.agent_description,
            "url": f"http://localhost:{settings.agent_port}",
            "version": "0.1.0",
            "protocolVersion": "0.3.0",
            "skills": [
                {
                    "id": "code",
                    "name": "code",
                    "description": f"run coding tasks with the {state.harness.name} harness",
                    "tags": ["coding", state.harness.name],
                    "inputModes": ["application/json"],
                    "outputModes": ["application/json"],
                }
            ],
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
                "stateTransitionHistory": True,
            },
            # RemoteAgent.process_message takes the A2A path on exactly this check.
            "supportedProtocols": ["jsonrpc"],
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
        }

    @app.get("/tools")
    async def tools() -> Dict[str, Any]:
        return {"agent": settings.agent_name, "tools": state.harness.tools()}

    @app.get("/memory/events")
    async def memory_events(limit: int = 100, session_id: Optional[str] = None) -> JSONResponse:
        limit = min(limit, 1000)
        if session_id:
            events = list(state.events.get(session_id, []))
        else:
            events = [e for evs in state.events.values() for e in evs]
        events = events[-limit:]
        return JSONResponse({"agent": settings.agent_name, "events": events, "total": len(events)})

    @app.get("/memory/sessions")
    async def memory_sessions() -> JSONResponse:
        sessions = list(state.events.keys())
        return JSONResponse(
            {"agent": settings.agent_name, "sessions": sessions, "total": len(sessions)}
        )

    @app.get("/sessions")
    async def sessions() -> Dict[str, Any]:
        """Driver extra — per-session workspaces have no home on AgentStatus."""
        return {
            "sessions": [
                {
                    "id": sid,
                    "workspace": state.workspaces.get(sid, ""),
                    "events": len(state.events.get(sid, [])),
                }
                for sid in state.events
            ]
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        messages = body.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="messages are required")
        prompt = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        session_id = _session_id(request, body)

        if not body.get("stream"):
            final = await state.collect(prompt, session_id)
            return JSONResponse(
                {
                    "id": session_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": settings.model_name,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": final},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )

        async def stream() -> AsyncIterator[str]:
            # Progress events ride inside delta.content as a JSON *string*; both
            # clients detect them by "content starts with { and parses".
            async for kind, payload in state.run(prompt, session_id):
                content = json.dumps(payload) if kind == "progress" else payload
                yield f"data: {json.dumps(_chunk(state, session_id, content))}\n\n"
            yield f"data: {json.dumps(_chunk(state, session_id, None, 'stop'))}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/")
    async def a2a(request: Request) -> JSONResponse:
        try:
            req = await request.json()
        except Exception:
            return _rpc_error(None, -32700, "Parse error")

        method = req.get("method")
        params = req.get("params") or {}
        rid = req.get("id")

        if method in ("SendMessage", "tasks/send", "message/send"):
            message = params.get("message") or {}
            text = " ".join(
                p.get("text", "") for p in message.get("parts", []) if p.get("type") == "text"
            )
            session_id = params.get("contextId") or str(uuid.uuid4())
            task_id = str(uuid.uuid4())
            task = {
                "id": task_id,
                "contextId": session_id,
                "status": {"state": "working"},
                "artifacts": [],
                "history": [message] if message else [],
            }
            state.tasks[task_id] = task
            try:
                final = await state.collect(text, session_id)
            except Exception as exc:  # pragma: no cover - harness failure path
                task["status"] = {"state": "failed", "message": str(exc)}
                return _rpc_error(rid, -32603, f"Harness failed: {exc}")
            task["status"] = {"state": "completed"}
            task["artifacts"] = [{"parts": [{"type": "text", "text": final}]}]
            task["history"].append({"role": "agent", "parts": [{"type": "text", "text": final}]})
            return _rpc_ok(rid, task)

        if method in ("GetTask", "tasks/get"):
            task = state.tasks.get(params.get("id") or params.get("taskId"))
            return _rpc_ok(rid, task) if task else _rpc_error(rid, -32001, "Task not found")

        if method in ("ListTasks", "tasks/list"):
            return _rpc_ok(rid, {"tasks": list(state.tasks.values())})

        if method in ("CancelTask", "tasks/cancel"):
            task = state.tasks.get(params.get("id") or params.get("taskId"))
            if not task:
                return _rpc_error(rid, -32001, "Task not found")
            task["status"] = {"state": "canceled"}
            return _rpc_ok(rid, task)

        return _rpc_error(rid, -32601, f"Method not found: {method}")

    return app


def _rpc_ok(rid: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})


def _rpc_error(rid: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def get_app() -> FastAPI:
    """Uvicorn factory entrypoint."""
    return create_app()
