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

import asyncio
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

from kaos_memory.config import MemorySettings
from kaos_memory.contract import (
    FailureMode,
    ForgetRequest,
    ForgetResponse,
    MediumTermContext,
    RecallRequest,
    RecallResponse,
    Scope,
    ShortTermContext,
    Turn,
    WriteRequest,
    WriteResponse,
)
from kaos_memory.stores import (
    LongTermStore,
    ModelClient,
    Scheduler,
    ShortTermStore,
)
from kaos_memory.telemetry import setup_telemetry

tracer = trace.get_tracer("kaos.memory")
logger = logging.getLogger("kaos.memory.background")


# --------------------------------------------------------------------------- #
# Presentation — render recalled memory into a deterministic injectable block.
# --------------------------------------------------------------------------- #


def _fact_text(fact: Dict[str, Any]) -> str:
    """Extract the human-readable text from a Mem0 result dict."""
    return fact.get("memory") or fact.get("text") or ""


def assemble_block(facts: List[Dict[str, Any]]) -> str:
    """Render the long-term memory block. Empty input yields an empty block.

    The block is plain text the runtime injects into the agent's system context (as
    leading context, not fabricated prior turns). It carries only long-term facts:
    conversational continuity — the rolling summary and the recent verbatim window — is
    replayed separately as reconstructed message history, so rendering it here too would
    duplicate it in the prompt. The summary and recent turns are returned in their own
    response fields for that replay.
    """
    fact_lines = [f"- {_fact_text(f)}" for f in facts if _fact_text(f)]
    if not fact_lines:
        return ""
    return "## Relevant memory\n" + "\n".join(fact_lines)


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
    default_failure_mode: FailureMode = "soft"

    def _resolve_failure_mode(self, requested: Optional[FailureMode]) -> FailureMode:
        """Layer the failure mode: an explicit per-request value wins, otherwise the
        service default (itself sourced from the store configuration, defaulting to soft)."""
        return requested if requested is not None else self.default_failure_mode

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
        to conversational-tier-only context rather than failing the request."""
        with tracer.start_as_current_span("kaos.memory.recall") as span:
            span.set_attribute("kaos.memory.scope_level", req.scope.level.value)
            facts: list = []
            degraded = False
            try:
                facts = self.longterm.recall(req.scope, req.query, top_k=req.top_k)
            except Exception:
                degraded = True

            summary, recent = "", []
            if req.include_short_term and req.scope.session_id is not None:
                summary = self.short_term.summary(req.scope)
                recent = self.short_term.active_window(
                    req.scope, token_budget=req.short_term_token_budget
                )

            span.set_attribute("kaos.memory.degraded", degraded)
            span.set_attribute("kaos.memory.fact_count", len(facts))
            block = assemble_block(facts)
            return RecallResponse(
                facts=facts,
                short_term=ShortTermContext(recent=recent),
                medium_term=MediumTermContext(summary=summary),
                block=block,
                degraded=degraded,
            )

    def write(self, req: WriteRequest) -> WriteResponse:
        """Append one or more turns to the short-term window synchronously; when the appends
        evict a batch, schedule long-term extraction of *that evicted batch* off the response
        path.

        A single call may carry a batch of turns so the runtime persists a whole interaction
        in one request. Extraction is not per-turn: new turns enter the verbatim window, and
        when the window crosses its compaction trigger the oldest turns are evicted and returned.
        The evicted turns across the batch are collected and long-term fact extraction consumes
        them once (and the medium-term digest folds the same rows independently inside the
        store), so the model runs once per fold over a coherent batch rather than once per
        message. The synchronous append is the cheap durable path; ``strict`` surfaces a
        failure as an exception (the handler maps it to an error), ``soft`` returns a degraded
        acknowledgement instead of failing the request.
        """
        with tracer.start_as_current_span("kaos.memory.write") as span:
            span.set_attribute("kaos.memory.scope_level", req.scope.level.value)
            strict = self._resolve_failure_mode(req.failure_mode) == "strict"

            try:
                evicted = self.short_term.add(
                    req.scope, [(turn.role, turn.content) for turn in req.turns]
                )
            except Exception:
                span.set_attribute("kaos.memory.degraded", True)
                if strict:
                    raise
                return WriteResponse(accepted=True, scheduled=False, degraded=True)

            span.set_attribute("kaos.memory.turns", len(req.turns))
            span.set_attribute("kaos.memory.evicted", len(evicted))
            if not evicted:
                # The turns are buffered in the window; nothing has left it yet, so there is
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
            self.short_term.delete(req.scope)
            try:
                self.longterm.delete_scope(req.scope)
            except Exception:
                span.set_attribute("kaos.memory.degraded", True)
                if self._resolve_failure_mode(req.failure_mode) == "strict":
                    raise
                return ForgetResponse(forgotten=True, degraded=True)
            return ForgetResponse(forgotten=True, degraded=False)


# --------------------------------------------------------------------------- #
# App factory and entrypoint.
# --------------------------------------------------------------------------- #


def create_app(service: MemoryService, request_concurrency: int = 8) -> FastAPI:
    """Build the FastAPI app bound to a ``MemoryService``.

    The request handlers are async, but the store and Mem0 calls they make are synchronous
    (Mem0's client is sync and its async surface only wraps threads). Rather than block the
    event loop or lean on the server's implicit threadpool, blocking work is dispatched to a
    KAOS-owned bounded executor — the explicit Mem0 isolation boundary — sized by
    ``request_concurrency``. Native async database access is a later optimisation; here the
    synchronous short-term path is cheap and runs behind the same boundary.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Drain pending background work if the scheduler is a drainable runner.
        drain = getattr(app.state.memory.scheduler, "shutdown", None)
        if callable(drain):
            drain(wait=True)
        app.state.request_pool.shutdown(wait=True)

    app = FastAPI(title="KAOS Memory Service", lifespan=lifespan)
    app.state.memory = service
    app.state.request_pool = ThreadPoolExecutor(max_workers=request_concurrency)
    setup_telemetry(app)

    async def _offload(fn: Callable[[], Any]) -> Any:
        """Run a blocking store/Mem0 call on the bounded executor, off the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(app.state.request_pool, fn)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Liveness: the process is up and serving. Independent of store state."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Readiness: both stores are reachable. 503 when any store probe fails."""
        result = await _offload(app.state.memory.readiness)
        code = 200 if result["ready"] else 503
        return JSONResponse(result, status_code=code)

    @app.post("/v1/recall", response_model=RecallResponse)
    async def recall(req: RecallRequest) -> RecallResponse:
        """Synchronous recall: assemble long-term facts and short-term context for a scope."""
        return await _offload(lambda: app.state.memory.recall(req))

    @app.post("/v1/write", response_model=WriteResponse)
    async def write(req: WriteRequest) -> JSONResponse:
        """Record turns: durable short-term append now, long-term extraction scheduled on fold."""
        try:
            result = await _offload(lambda: app.state.memory.write(req))
        except Exception as exc:
            return JSONResponse(
                {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )
        return JSONResponse(result.model_dump(), status_code=202 if result.scheduled else 200)

    @app.post("/v1/forget", response_model=ForgetResponse)
    async def forget(req: ForgetRequest) -> JSONResponse:
        """Erase a scope across both tiers."""
        try:
            result = await _offload(lambda: app.state.memory.forget(req))
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
    longterm = LongTermStore(
        storage,
        settings.summarization(),
        settings.embedding(),
        system_prompt=settings.extraction_system_prompt or None,
    )
    summarizer = ModelClient(
        settings.summarization(), system_prompt=settings.summarization_system_prompt or None
    ).as_summarizer()
    short_term = ShortTermStore(
        settings.storage_type,
        settings.short_term_target(),
        settings.short_term_tier(),
        summarizer,
        scheduler=runner,
        group=storage.resolved().collection_name,
    )
    return MemoryService(
        longterm=longterm,
        short_term=short_term,
        scheduler=runner,
        default_failure_mode=settings.default_failure_mode,
    )


def main() -> None:
    """Entrypoint: build the service from the environment and serve it with uvicorn."""
    settings = MemorySettings()
    app = create_app(build_service(settings), request_concurrency=settings.request_concurrency)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
