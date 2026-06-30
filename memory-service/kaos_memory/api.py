"""HTTP request/response schemas for the memory service.

These mirror the memory contract: a scope context the runtime injects, a query and
presentation knobs for recall, and the assembled recall response. The schemas are
deliberately thin wrappers over the store-level value objects so the service does not
re-shape engine output — recalled facts pass through with their native fields.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from kaos_memory.scope import Scope


class RecallRequest(BaseModel):
    """Synchronous recall: assemble context visible at ``scope`` for ``query``."""

    scope: Scope
    query: str
    top_k: int = 10
    include_working: bool = True
    working_token_budget: Optional[int] = None


FailureMode = str  # "soft" | "strict"


class WriteRequest(BaseModel):
    """Record a turn: append to the working tier synchronously, extract long-term async.

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
    """Acknowledges a write. ``scheduled`` indicates long-term extraction was queued;
    ``degraded`` is set when a fail-soft request swallowed a scheduling error."""

    accepted: bool = True
    scheduled: bool = False
    degraded: bool = False


class WorkingContext(BaseModel):
    """The working-tier slice of a recall response."""

    summary: str = ""
    recent: List[Tuple[str, str]] = Field(default_factory=list)


class RecallResponse(BaseModel):
    """Assembled recall context: native long-term facts, working context, and a block.

    ``facts`` are Mem0's native result dicts (memory text, score, id, metadata),
    passed through unmodified. ``block`` is the deterministic structured text the
    runtime injects into the system context. ``degraded`` is set when long-term
    recall failed and only working context is present.
    """

    facts: List[Dict[str, Any]] = Field(default_factory=list)
    working: WorkingContext = Field(default_factory=WorkingContext)
    block: str = ""
    degraded: bool = False
