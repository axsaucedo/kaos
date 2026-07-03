"""Central memory service: the HTTP surface, request/response schemas, block
presentation, bounded background runner and the entrypoint wiring.

The service composes the two atomic stores (long-term over Mem0, short-term
relational buffer) into one KAOS-owned process so agents call a shared service
rather than embedding the engine. This module holds:

- the HTTP request/response schemas that mirror the memory contract;
- the deterministic recall block renderer injected into the agent's context;
- a bounded fire-and-forget background runner for off-path work;
- the ``MemoryService`` that the request handlers operate on;
- the FastAPI app factory and the ``main`` entrypoint that builds the real
  stores from the environment.

Keeping the inbound HTTP layer here (separate from ``stores.py``, which owns the
storage engine the service calls) is the one intentional split: the store module
is the outbound dependency, this module is the inbound edge.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, Field

from kaos_memory.config import MemorySettings
from kaos_memory.stores import (
    LongTermStore,
    ModelClient,
    Scheduler,
    Scope,
    ShortTermStore,
)

tracer = trace.get_tracer("kaos.memory")
logger = logging.getLogger("kaos.memory.background")


# --------------------------------------------------------------------------- #
# HTTP schemas — thin wrappers over the store-level value objects.
# --------------------------------------------------------------------------- #


class RecallRequest(BaseModel):
    """Synchronous recall: assemble context visible at ``scope`` for ``query``."""

    scope: Scope
    query: str
    top_k: int = 10
    include_short_term: bool = True
    short_term_token_budget: Optional[int] = None


FailureMode = str  # "soft" | "strict"


class WriteRequest(BaseModel):
    """Record a turn: append to the short-term window synchronously; long-term extraction
    runs later, per fold, over the batch the append evicts.

    ``infer`` controls whether the engine extracts facts (vs storing raw). ``failure_mode``
    selects fail-soft (swallow long-term scheduling errors, return degraded) or strict
    (surface failures as an error).
    """

    scope: Scope
    role: str
    content: str
    infer: bool = True
    failure_mode: FailureMode = "soft"


class WriteResponse(BaseModel):
    """Acknowledges a write. ``scheduled`` indicates the append evicted a batch and long-term
    extraction of that batch was queued (writes that only buffer the turn return
    ``scheduled=False``); ``degraded`` is set when a fail-soft request swallowed a
    scheduling error."""

    accepted: bool = True
    scheduled: bool = False
    degraded: bool = False


class ForgetRequest(BaseModel):
    """Erase a scope: clear its short-term tier and delete its long-term memories."""

    scope: Scope
    failure_mode: FailureMode = "soft"


class ForgetResponse(BaseModel):
    """Acknowledges a forget. ``degraded`` is set when the long-term erasure failed
    under fail-soft (the short-term tier was still cleared)."""

    forgotten: bool = True
    degraded: bool = False


class ShortTermContext(BaseModel):
    """The short-term tier slice of a recall response."""

    summary: str = ""
    recent: List[Tuple[str, str]] = Field(default_factory=list)


class RecallResponse(BaseModel):
    """Assembled recall context: native long-term facts, short-term context, and a block.

    ``facts`` are Mem0's native result dicts (memory text, score, id, metadata),
    passed through unmodified. ``block`` is the deterministic structured text the
    runtime injects into the system context. ``degraded`` is set when long-term
    recall failed and only short-term context is present.
    """

    facts: List[Dict[str, Any]] = Field(default_factory=list)
    short_term: ShortTermContext = Field(default_factory=ShortTermContext)
    block: str = ""
    degraded: bool = False


# --------------------------------------------------------------------------- #
# Presentation — render recalled memory into a deterministic injectable block.
# --------------------------------------------------------------------------- #


def _fact_text(fact: Dict[str, Any]) -> str:
    """Extract the human-readable text from a Mem0 result dict."""
    return fact.get("memory") or fact.get("text") or ""


def assemble_block(
    facts: List[Dict[str, Any]],
    summary: str,
    recent: List[Tuple[str, str]],
) -> str:
    """Render the structured memory block. Empty inputs yield an empty block.

    The block is plain text the runtime injects into the agent's system context (not
    as fabricated prior turns). It is always-on and cheap, rendering whatever context
    is available — long-term facts, a rolling summary, recent verbatim turns.
    """
    sections: List[str] = []

    fact_lines = [f"- {_fact_text(f)}" for f in facts if _fact_text(f)]
    if fact_lines:
        sections.append("## Relevant memory\n" + "\n".join(fact_lines))

    if summary.strip():
        sections.append("## Conversation summary\n" + summary.strip())

    if recent:
        turns = "\n".join(f"{role}: {content}" for role, content in recent)
        sections.append("## Recent turns\n" + turns)

    return "\n\n".join(sections)


# --------------------------------------------------------------------------- #
# Background runner — bounded fire-and-forget off-path work.
# --------------------------------------------------------------------------- #

#: Invoked when a task gives up after exhausting retries (the exception is passed).
GiveupHook = Callable[[BaseException], None]


class BackgroundRunner:
    """Runs thunks on a bounded threadpool with bounded retry and graceful drain.

    Long-term extraction, consolidation, forgetting and short-term summary folding run
    off the request path. This runner bounds their concurrency, retries transient
    failures a fixed number of times, and gives up cleanly (without crashing the
    service) when retries are exhausted. Pending work drains on shutdown.

    The service handlers are synchronous (FastAPI runs them on a threadpool), so the
    runner is thread-based: a ``ThreadPoolExecutor`` caps concurrency at ``concurrency``
    workers, the natural fit for the sync server model.
    """

    def __init__(
        self,
        concurrency: int = 4,
        max_retries: int = 2,
        retry_delay: float = 0.0,
        on_giveup: Optional[GiveupHook] = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.concurrency = concurrency
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.on_giveup = on_giveup
        self.failures = 0
        self._executor = ThreadPoolExecutor(max_workers=concurrency)

    def submit(self, thunk: Callable[[], None]) -> None:
        """Schedule ``thunk`` to run off the response path. Never blocks the caller."""
        self._executor.submit(self._run_with_retry, thunk)

    # Usable directly as a Scheduler (Callable[[thunk], None]).
    __call__ = submit

    def _run_with_retry(self, thunk: Callable[[], None]) -> None:
        attempts = self.max_retries + 1
        last: Optional[BaseException] = None
        for attempt in range(attempts):
            try:
                thunk()
                return
            except Exception as exc:  # bounded retry; never propagate out of the worker
                last = exc
                if attempt + 1 < attempts and self.retry_delay:
                    time.sleep(self.retry_delay)
        self.failures += 1
        logger.warning("background task gave up after %d attempts: %s", attempts, last)
        if self.on_giveup is not None and last is not None:
            try:
                self.on_giveup(last)
            except Exception:  # never let the give-up hook crash a worker
                logger.exception("on_giveup hook raised")

    def shutdown(self, wait: bool = True) -> None:
        """Drain pending work and stop accepting new tasks."""
        self._executor.shutdown(wait=wait)


def _thread_scheduler(thunk: Callable[[], None]) -> None:
    """Default scheduler: run the thunk on a daemon thread (replaced by the bounded
    background runner when one is supplied)."""
    import threading

    threading.Thread(target=thunk, daemon=True).start()


# --------------------------------------------------------------------------- #
# MemoryService — the request handlers operating over live store instances.
# --------------------------------------------------------------------------- #


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
                recent = self.short_term.active_window(
                    req.scope, token_budget=req.short_term_token_budget
                )

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
        """Append a turn to the short-term window synchronously; when the append evicts a
        batch, schedule long-term extraction of *that evicted batch* off the response path.

        Extraction is not per-turn. New turns enter the verbatim window; when the window
        crosses its water mark the oldest turns are evicted, and ``add`` returns that
        evicted batch. Long-term fact extraction consumes the evicted batch (and the
        medium-term digest folds the same rows independently inside the store), so the
        model runs once per fold over a coherent batch rather than once per message. The
        synchronous append is the cheap durable path; ``strict`` surfaces a failure as an
        exception (the handler maps it to an error), ``soft`` returns a degraded
        acknowledgement instead of failing the request.
        """
        with tracer.start_as_current_span("kaos.memory.write") as span:
            span.set_attribute("kaos.memory.scope_level", req.scope.level.value)
            strict = req.failure_mode == "strict"

            try:
                evicted = self.short_term.add(req.scope, req.role, req.content)
            except Exception:
                span.set_attribute("kaos.memory.degraded", True)
                if strict:
                    raise
                return WriteResponse(accepted=True, scheduled=False, degraded=True)

            span.set_attribute("kaos.memory.evicted", len(evicted))
            if not evicted:
                # The turn is buffered in the window; nothing has left it yet, so there is
                # no batch to consolidate. Extraction runs later, when a fold evicts.
                return WriteResponse(accepted=True, scheduled=False, degraded=False)

            messages = [{"role": role, "content": content} for role, content in evicted]

            def _extract() -> None:
                with tracer.start_as_current_span("kaos.memory.consolidate"):
                    self.longterm.add(req.scope, messages, infer=req.infer)

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
        the response but the short-term tier is still cleared."""
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


# --------------------------------------------------------------------------- #
# App factory and entrypoint.
# --------------------------------------------------------------------------- #


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
        """Record a turn: durable short-term add now, long-term extraction scheduled."""
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


def build_service(settings: MemorySettings) -> MemoryService:
    """Construct the long-term and short-term stores and wrap them in a ``MemoryService``.

    A single bounded background runner backs both off-path paths: short-term summary
    folding (injected as the store's scheduler) and long-term extraction (the service
    scheduler), so all deferred work shares one bounded, drainable threadpool.
    """
    storage = settings.storage()
    runner = BackgroundRunner(
        concurrency=settings.extraction_concurrency,
        max_retries=settings.extraction_max_retries,
    )
    longterm = LongTermStore(storage, settings.summarization(), settings.embedding())
    summarizer = ModelClient(settings.summarization()).as_summarizer()
    short_term = ShortTermStore(
        settings.storage_type,
        settings.short_term_target(),
        settings.short_term_tier(),
        summarizer,
        scheduler=runner,
    )
    return MemoryService(longterm=longterm, short_term=short_term, scheduler=runner)


def main() -> None:
    """Entrypoint: build the service from the environment and serve it with uvicorn."""
    settings = MemorySettings()
    app = create_app(build_service(settings))
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
