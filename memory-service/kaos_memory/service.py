"""Central memory service: a FastAPI app exposing the memory contract over HTTP.

The service composes the two atomic stores (long-term over Mem0, working-tier
relational buffer) into one KAOS-owned process so agents call a shared service
rather than embedding the engine. This module holds the app factory and the
liveness/readiness surface; the recall, write, forget and background machinery
are layered on by the rest of the package.

The app is constructed from already-resolved store instances so it is trivially
testable: tests pass fakes or offline-configured real stores; the ``__main__``
entrypoint builds the real stores from the environment.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from kaos_memory.api import (
    RecallRequest,
    RecallResponse,
    WorkingContext,
    WriteRequest,
    WriteResponse,
)
from kaos_memory.longterm import LongTermStore
from kaos_memory.presentation import assemble_block
from kaos_memory.working import WorkingStore

#: Schedules a fire-and-forget extraction thunk off the response path.
Scheduler = Callable[[Callable[[], None]], None]


def _thread_scheduler(thunk: Callable[[], None]) -> None:
    """Default scheduler: run the thunk on a daemon thread (replaced by the bounded
    background runner when one is supplied)."""
    import threading

    threading.Thread(target=thunk, daemon=True).start()


@dataclass
class MemoryService:
    """Holds the live store instances the request handlers operate on."""

    longterm: LongTermStore
    working: WorkingStore
    scheduler: Scheduler = field(default=_thread_scheduler)

    def readiness(self) -> dict:
        """Probe both stores and report per-store reachability.

        Reflects store reachability only — models bind lazily on first use, so an
        as-yet-unreachable ModelAPI must not fail readiness. Returns a mapping of
        ``{"ready": bool, "stores": {name: ok|error}}``.
        """
        stores: dict[str, object] = {}
        ok = True
        for name, probe in (("working", self.working.ping), ("longterm", self.longterm.ping)):
            try:
                probe()
                stores[name] = True
            except Exception as exc:  # reachability probe: any failure means not-ready
                stores[name] = f"{type(exc).__name__}: {exc}"
                ok = False
        return {"ready": ok, "stores": stores}

    def recall(self, req: RecallRequest) -> RecallResponse:
        """Assemble recall context for a scope. Fail-soft: long-term errors degrade
        to working-only context rather than failing the request."""
        facts: list = []
        degraded = False
        try:
            facts = self.longterm.recall(req.scope, req.query, top_k=req.top_k)
        except Exception:
            degraded = True

        summary, recent = "", []
        if req.include_working:
            summary = self.working.summary(req.scope)
            recent = self.working.recent(req.scope, token_budget=req.working_token_budget)

        block = assemble_block(facts, summary, recent)
        return RecallResponse(
            facts=facts,
            working=WorkingContext(summary=summary, recent=recent),
            block=block,
            degraded=degraded,
        )

    def write(self, req: WriteRequest) -> WriteResponse:
        """Append a turn to the working tier synchronously, then schedule long-term
        extraction off the response path so the call returns immediately.

        The synchronous working append is the cheap durable path. ``strict`` surfaces a
        failure as an exception (the handler maps it to an error); ``soft`` returns a
        degraded acknowledgement instead of failing the request.
        """
        strict = req.failure_mode == "strict"

        try:
            self.working.append(req.scope, req.role, req.content)
        except Exception:
            if strict:
                raise
            return WriteResponse(accepted=True, scheduled=False, degraded=True)

        def _extract() -> None:
            self.longterm.write(
                req.scope, [{"role": req.role, "content": req.content}], infer=req.infer
            )

        try:
            self.scheduler(_extract)
        except Exception:
            if strict:
                raise
            return WriteResponse(accepted=True, scheduled=False, degraded=True)

        return WriteResponse(accepted=True, scheduled=True, degraded=False)


def create_app(service: MemoryService) -> FastAPI:
    """Build the FastAPI app bound to a ``MemoryService``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Drain pending background work if the scheduler is a drainable runner.
        drain = getattr(app.state.memory.scheduler, "shutdown", None)
        if callable(drain):
            drain(wait=True)

    app = FastAPI(title="KAOS Memory Service", lifespan=lifespan)
    app.state.memory = service

    @app.get("/healthz")
    def healthz() -> dict:
        """Liveness: the process is up and serving. Independent of store state."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        """Readiness: both stores are reachable. 503 when any store probe fails."""
        result = app.state.memory.readiness()
        code = 200 if result["ready"] else 503
        return JSONResponse(result, status_code=code)

    @app.post("/v1/recall", response_model=RecallResponse)
    def recall(req: RecallRequest) -> RecallResponse:
        """Synchronous recall: assemble long-term facts and working context for a scope."""
        return app.state.memory.recall(req)

    @app.post("/v1/write", response_model=WriteResponse)
    def write(req: WriteRequest) -> JSONResponse:
        """Record a turn: durable working append now, long-term extraction scheduled."""
        try:
            result = app.state.memory.write(req)
        except Exception as exc:
            return JSONResponse(
                {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )
        return JSONResponse(result.model_dump(), status_code=202 if result.scheduled else 200)

    return app


def app_from_service(
    longterm: LongTermStore, working: WorkingStore, _service: Optional[MemoryService] = None
) -> FastAPI:
    """Convenience constructor used by tests: wrap stores and build the app."""
    return create_app(MemoryService(longterm=longterm, working=working))
