"""The memory service HTTP client.

:class:`MemoryServiceClient` is the framework-agnostic client for the KAOS memory
service. It speaks the recall, write, and forget endpoints of :mod:`kaos_memory.contract` over HTTP and
treats every call as best-effort: transport failures and degraded responses never
raise (unless a write/forget explicitly selects ``failure_mode="strict"``), so a
caller's request path is never taken down by memory being unavailable.

It has no dependency on any agent framework — the Pydantic AI adapter that wraps
it lives in :mod:`kaos_memory.pydantic_ai`. Recall returns a :class:`RecalledMemory`
carrying the three tiers (long-term facts, the medium-term digest, the short-term
window) plus the ready-to-inject block.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from opentelemetry import trace as trace_api

from kaos_memory.contract import Attribution, Scope

logger = logging.getLogger("kaos.memory.client")

_TRACER_NAME = "kaos.memory"


@dataclass
class ShortTermRecall:
    """Short-term tier slice of a recall: the verbatim active window, oldest first."""

    recent: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class MediumTermRecall:
    """Medium-term tier slice of a recall: the rolling conversation digest."""

    summary: str = ""


@dataclass
class RecalledMemory:
    """Assembled recall result across the three memory tiers, mirroring the service.

    ``facts`` are the long-term engine's native result records (text, score, id,
    metadata) passed through unmodified. ``short_term`` is the verbatim active window
    and ``medium_term`` is the rolling digest — the two conversational tiers the
    service returns as distinct blocks. ``block`` is the deterministic, ready-to-inject
    context block. ``degraded`` is set when the long-term tier was unavailable and only
    the conversational tiers are present — recall is best-effort and never aborts a call.

    ``recent`` and ``summary`` are convenience accessors onto the short-term and
    medium-term slices so existing call sites read a single field per tier.
    """

    facts: List[Dict[str, Any]] = field(default_factory=list)
    short_term: ShortTermRecall = field(default_factory=ShortTermRecall)
    medium_term: MediumTermRecall = field(default_factory=MediumTermRecall)
    block: str = ""
    degraded: bool = False

    @property
    def recent(self) -> List[Tuple[str, str]]:
        return self.short_term.recent

    @property
    def summary(self) -> str:
        return self.medium_term.summary

    @property
    def is_empty(self) -> bool:
        return not self.facts and not self.medium_term.summary and not self.short_term.recent


class MemoryServiceClient:
    """Best-effort HTTP client for the central memory service.

    Speaks ``/v1/recall``, ``/v1/write`` and ``/v1/forget`` at ``endpoint``. Recall
    degrades to an empty result on any failure; write/forget are fail-soft by default
    and only raise when the caller passes ``failure_mode="strict"``. ``failure_mode`` is
    omitted from the request unless explicitly set, so the service's configured default
    governs the call.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 10.0,
        recall_timeout: float = 5.0,
        client: Optional[httpx.AsyncClient] = None,
    ):
        if not endpoint:
            raise ValueError("MemoryServiceClient requires a service endpoint")
        self.endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._recall_timeout = recall_timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        logger.info(f"MemoryServiceClient initialized -> {self.endpoint}")

    async def recall(
        self,
        scope: Scope,
        query: str,
        *,
        top_k: int = 10,
        include_short_term: bool = True,
        token_budget: Optional[int] = None,
    ) -> RecalledMemory:
        tracer = trace_api.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(
            "kaos.memory.recall",
            attributes={"kaos.memory.scope_level": scope.level.value},
        ) as span:
            payload: Dict[str, Any] = {
                "scope": scope.model_dump(mode="json"),
                "query": query,
                "top_k": top_k,
                "include_short_term": include_short_term,
            }
            if token_budget is not None:
                payload["short_term_token_budget"] = token_budget
            try:
                resp = await self._client.post(
                    f"{self.endpoint}/v1/recall", json=payload, timeout=self._recall_timeout
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"Memory recall failed, degrading to empty context: {e}")
                span.set_attribute("kaos.memory.degraded", True)
                return RecalledMemory(degraded=True)

            short_term = data.get("short_term") or {}
            medium_term = data.get("medium_term") or {}
            recalled = RecalledMemory(
                facts=data.get("facts", []),
                short_term=ShortTermRecall(recent=[tuple(r) for r in short_term.get("recent", [])]),
                medium_term=MediumTermRecall(summary=medium_term.get("summary", "")),
                block=data.get("block", ""),
                degraded=bool(data.get("degraded", False)),
            )
            span.set_attribute("kaos.memory.degraded", recalled.degraded)
            span.set_attribute("kaos.memory.fact_count", len(recalled.facts))
            return recalled

    async def write(
        self,
        attribution: Attribution,
        turns: List[Tuple[str, str]],
        *,
        infer: bool = True,
        failure_mode: Optional[str] = None,
    ) -> bool:
        tracer = trace_api.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span("kaos.memory.write") as span:
            payload: Dict[str, Any] = {
                "attribution": attribution.model_dump(mode="json"),
                "turns": [{"role": role, "content": content} for role, content in turns],
                "infer": infer,
            }
            if failure_mode:
                payload["failure_mode"] = failure_mode
            span.set_attribute("kaos.memory.turns", len(turns))
            try:
                resp = await self._client.post(
                    f"{self.endpoint}/v1/write", json=payload, timeout=self._timeout
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                if failure_mode == "strict":
                    raise
                logger.warning(f"Memory write failed (fail-soft): {e}")
                span.set_attribute("kaos.memory.degraded", True)
                return False
            span.set_attribute("kaos.memory.scheduled", bool(data.get("scheduled", False)))
            span.set_attribute("kaos.memory.degraded", bool(data.get("degraded", False)))
            return bool(data.get("accepted", True))

    async def forget(self, scope: Scope, *, failure_mode: Optional[str] = None) -> bool:
        tracer = trace_api.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(
            "kaos.memory.forget",
            attributes={"kaos.memory.scope_level": scope.level.value},
        ) as span:
            payload: Dict[str, Any] = {"scope": scope.model_dump(mode="json")}
            if failure_mode:
                payload["failure_mode"] = failure_mode
            try:
                resp = await self._client.post(
                    f"{self.endpoint}/v1/forget", json=payload, timeout=self._timeout
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                if failure_mode == "strict":
                    raise
                logger.warning(f"Memory forget failed (fail-soft): {e}")
                span.set_attribute("kaos.memory.degraded", True)
                return False
            span.set_attribute("kaos.memory.degraded", bool(data.get("degraded", False)))
            return bool(data.get("forgotten", True))

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception as e:
            logger.debug(f"MemoryServiceClient close failed: {e}")
