"""Central memory service: a FastAPI app exposing the memory contract over HTTP.

The service composes the two atomic stores (long-term over Mem0, short-term
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
from opentelemetry import trace

from kaos_memory.api import (
    ForgetRequest,
    ForgetResponse,
    RecallRequest,
    RecallResponse,
    ShortTermContext,
    WriteRequest,
    WriteResponse,
)
from kaos_memory.longterm import LongTermStore
from kaos_memory.presentation import assemble_block
from kaos_memory.shortterm import ShortTermStore

tracer = trace.get_tracer("kaos.memory")

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
    short_term: ShortTermStore
    scheduler: Scheduler = field(default=_thread_scheduler)

    def readiness(self) -> dict:
        """Probe both stores and report per-store reachability.

        Reflects store reachability only — models bind lazily on first use, so an
        as-yet-unreachable ModelAPI must not fail readiness. Returns a mapping of
        ``{"ready": bool, "stores": {name: ok|error}}``.
        """
        stores: dict[str, object] = {}
        ok = True
        for name, probe in (("short_term", self.short_term.ping), ("longterm", self.longterm.ping)):
            try:
                probe()
                stores[name] = True
            except Exception as exc:  # reachability probe: any failure means not-ready
                stores[name] = f"{type(exc).__name__}: {exc}"
                ok = False
        return {"ready": ok, "stores": stores}

    def recall(self, req: RecallRequest) -> RecallResponse:
        """Assemble recall context for a scope. Fail-soft: long-term errors degrade
        to short-term-only context rather than failing the request."""
        with tracer.start_as_current_span("kaos.memory.recall") as span:
            span.set_attribute("kaos.memory.scope_level", req.scope.level.value)
            facts: list = []
            degraded = False
            try:
                facts = self.longterm.recall(req.scope, req.query, top_k=req.top_k)
            except Exception:
                degraded = True

            summary, recent = "", []
            if req.include_short_term:
                summary = self.short_term.summary(req.scope)
                recent = self.short_term.recent(req.scope, token_budget=req.short_term_token_budget)

            span.set_attribute("kaos.memory.degraded", degraded)
            span.set_attribute("kaos.memory.fact_count", len(facts))
            block = assemble_block(facts, summary, recent)
            return RecallResponse(
                facts=facts,
                short_term=ShortTermContext(summary=summary, recent=recent),
                block=block,
                degraded=degraded,
            )

    def write(self, req: WriteRequest) -> WriteResponse:
        """Append a turn to the short-term tier synchronously, then schedule long-term
        extraction off the response path so the call returns immediately.

        The synchronous short-term append is the cheap durable path. ``strict`` surfaces a
        failure as an exception (the handler maps it to an error); ``soft`` returns a
        degraded acknowledgement instead of failing the request.
        """
        with tracer.start_as_current_span("kaos.memory.write") as span:
            span.set_attribute("kaos.memory.scope_level", req.scope.level.value)
            strict = req.failure_mode == "strict"

            try:
                self.short_term.append(req.scope, req.role, req.content)
            except Exception:
                span.set_attribute("kaos.memory.degraded", True)
                if strict:
                    raise
                return WriteResponse(accepted=True, scheduled=False, degraded=True)

            def _extract() -> None:
                with tracer.start_as_current_span("kaos.memory.consolidate"):
                    self.longterm.write(
                        req.scope, [{"role": req.role, "content": req.content}], infer=req.infer
                    )

            try:
                self.scheduler(_extract)
            except Exception:
                span.set_attribute("kaos.memory.degraded", True)
                if strict:
                    raise
                return WriteResponse(accepted=True, scheduled=False, degraded=True)

            span.set_attribute("kaos.memory.scheduled", True)
            return WriteResponse(accepted=True, scheduled=True, degraded=False)

    def forget(self, req: ForgetRequest) -> ForgetResponse:
        """Erase a scope across both tiers: clear the short-term tier (durable) and delete
        the scope's long-term memories. Fail-soft: a long-term erasure error degrades
        the response but the short-term tier is still cleared. The synchronous cross-tier
        erasure guarantees are completed by the multi-tenancy work."""
        with tracer.start_as_current_span("kaos.memory.forget") as span:
            span.set_attribute("kaos.memory.scope_level", req.scope.level.value)
            self.short_term.clear(req.scope)
            try:
                self.longterm.delete_scope(req.scope)
            except Exception:
                span.set_attribute("kaos.memory.degraded", True)
                if req.failure_mode == "strict":
                    raise
                return ForgetResponse(forgotten=True, degraded=True)
            return ForgetResponse(forgotten=True, degraded=False)


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
        """Synchronous recall: assemble long-term facts and short-term context for a scope."""
        return app.state.memory.recall(req)

    @app.post("/v1/write", response_model=WriteResponse)
    def write(req: WriteRequest) -> JSONResponse:
        """Record a turn: durable short-term append now, long-term extraction scheduled."""
        try:
            result = app.state.memory.write(req)
        except Exception as exc:
            return JSONResponse(
                {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )
        return JSONResponse(result.model_dump(), status_code=202 if result.scheduled else 200)

    @app.post("/v1/forget", response_model=ForgetResponse)
    def forget(req: ForgetRequest) -> JSONResponse:
        """Erase a scope across both tiers."""
        try:
            result = app.state.memory.forget(req)
        except Exception as exc:
            return JSONResponse(
                {"forgotten": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )
        return JSONResponse(result.model_dump(), status_code=200)

    return app


def app_from_service(
    longterm: LongTermStore, short_term: ShortTermStore, _service: Optional[MemoryService] = None
) -> FastAPI:
    """Convenience constructor used by tests: wrap stores and build the app."""
    return create_app(MemoryService(longterm=longterm, short_term=short_term))
