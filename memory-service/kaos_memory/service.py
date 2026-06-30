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

from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from kaos_memory.api import RecallRequest, RecallResponse, WorkingContext
from kaos_memory.longterm import LongTermStore
from kaos_memory.presentation import assemble_block
from kaos_memory.working import WorkingStore


@dataclass
class MemoryService:
    """Holds the live store instances the request handlers operate on."""

    longterm: LongTermStore
    working: WorkingStore

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


def create_app(service: MemoryService) -> FastAPI:
    """Build the FastAPI app bound to a ``MemoryService``."""
    app = FastAPI(title="KAOS Memory Service")
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

    return app


def app_from_service(
    longterm: LongTermStore, working: WorkingStore, _service: Optional[MemoryService] = None
) -> FastAPI:
    """Convenience constructor used by tests: wrap stores and build the app."""
    return create_app(MemoryService(longterm=longterm, working=working))
