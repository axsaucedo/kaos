"""The memory service wire contract — scope identity and request/response schemas.

This module is the single source of truth for the HTTP contract between the
memory service and its clients. It carries no storage-engine or web-framework
dependencies (only Pydantic), so both the service (which serves these schemas)
and the client (which speaks them) import the same definitions rather than
maintaining parallel copies that can drift.

The scope value objects (:class:`ScopeLevel`, :class:`Scope`) identify whose
memory an operation touches; the request/response models mirror the four
endpoints (recall, write, forget). Owner-key mapping onto the storage engine is
kept here on :class:`Scope` because it depends only on the scope fields, but it
is exercised solely by the service.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

#: A write/forget failure mode: ``"soft"`` swallows long-term errors and returns
#: degraded; ``"strict"`` surfaces them. When omitted the service default applies.
FailureMode = str


class ScopeLevel(str, Enum):
    """The memory scope an operation targets.

    - ``AGENT``: only this agent (mapped to ``agent_id``).
    - ``USER``: all agents acting for a principal (mapped to ``user_id``).
    - ``GROUP``: every agent on the store (mapped to the reserved group owner).
    - ``SESSION``: a single run/conversation (mapped to ``run_id``).
    """

    AGENT = "agent"
    USER = "user"
    GROUP = "group"
    SESSION = "session"


class Scope(BaseModel):
    """Identifies the owner of a memory operation.

    Carries the principal, the agent's stable client id, and the session id, plus
    the selected ``level``. Only the field required by ``level`` must be present;
    the rest may be unset (an under-specified scope is representable here and is
    rejected by enforcement later, not by construction).

    The scope is always derived server-side from the authenticated request and
    the agent's verifiable identity; it is never read from model- or tool-supplied
    arguments.
    """

    level: ScopeLevel
    principal: Optional[str] = None
    agent_client_id: Optional[str] = None
    session_id: Optional[str] = None

    @model_validator(mode="after")
    def _normalise(self) -> "Scope":
        # Empty strings are treated as unset so they cannot be used as owner keys.
        for field in ("principal", "agent_client_id", "session_id"):
            value = getattr(self, field)
            if value is not None and value.strip() == "":
                object.__setattr__(self, field, None)
        return self

    def is_complete(self) -> bool:
        """Whether the field required by ``level`` is present (a usable owner key exists)."""
        if self.level is ScopeLevel.AGENT:
            return self.agent_client_id is not None
        if self.level is ScopeLevel.USER:
            return self.principal is not None
        if self.level is ScopeLevel.SESSION:
            return self.session_id is not None
        return True  # GROUP always resolves to the reserved owner.

    def owner_kwargs(self) -> Dict[str, Any]:
        """Return the single Mem0 entity owner selected by this scope.

        Entity-scoped operations use one of ``user_id`` / ``agent_id`` / ``run_id``.
        Group scope has no synthetic entity owner and raises instead of mapping to
        a sentinel.
        """
        if self.level is ScopeLevel.AGENT:
            if self.agent_client_id is None:
                raise ValueError("agent scope requires agent_client_id")
            return {"agent_id": self.agent_client_id}
        if self.level is ScopeLevel.USER:
            if self.principal is None:
                raise ValueError("user scope requires principal")
            return {"user_id": self.principal}
        if self.level is ScopeLevel.SESSION:
            if self.session_id is None:
                raise ValueError("session scope requires session_id")
            return {"run_id": self.session_id}
        raise ValueError("group scope has no Mem0 entity owner")

    def write_kwargs(self, group: Optional[str] = None) -> Dict[str, Any]:
        """Return compound Mem0 attribution for a long-term write.

        Entity ids identify every known contributor. The conversation and store
        group are custom metadata so they remain filterable without narrowing
        Mem0's deduplication candidates across sessions.
        """
        kwargs: Dict[str, Any] = {}
        if self.principal is not None:
            kwargs["user_id"] = self.principal
        if self.agent_client_id is not None:
            kwargs["agent_id"] = self.agent_client_id
        if not kwargs:
            raise ValueError("memory write requires principal or agent_client_id")

        metadata = {}
        if self.session_id is not None:
            metadata["kaos_run"] = self.session_id
        if group:
            metadata["kaos_group"] = group
        if metadata:
            kwargs["metadata"] = metadata
        return kwargs

    def search_filters(self, group: Optional[str] = None) -> Dict[str, Any]:
        """Return the Mem0 ``filters`` dict for a search at this scope.

        User and agent visibility use their native entity ids. Session and group
        visibility use custom attribution metadata plus Mem0's required entity
        wildcard compatibility convention.
        """
        if self.level is ScopeLevel.USER:
            if self.principal is None:
                raise ValueError("user scope requires principal")
            return {"user_id": self.principal}
        if self.level is ScopeLevel.AGENT:
            if self.agent_client_id is None:
                raise ValueError("agent scope requires agent_client_id")
            return {"agent_id": self.agent_client_id}
        if self.level is ScopeLevel.SESSION:
            if self.session_id is None:
                raise ValueError("session scope requires session_id")
            return {"user_id": "*", "kaos_run": self.session_id}
        if not group:
            raise ValueError("group scope requires the store group")
        return {"user_id": "*", "kaos_group": group}


def scope_key(scope: Scope) -> str:
    """Stable string key for a scope's short-term window (one owner key -> 'key:value')."""
    ((key, value),) = scope.owner_kwargs().items()
    return f"{key}:{value}"


# --------------------------------------------------------------------------- #
# Request/response schemas — the four endpoints of the memory contract.
# --------------------------------------------------------------------------- #


class RecallRequest(BaseModel):
    """Synchronous recall: assemble context visible at ``scope`` for ``query``."""

    scope: Scope
    query: str
    top_k: int = 10
    include_short_term: bool = True
    short_term_token_budget: Optional[int] = None


class Turn(BaseModel):
    """A single conversational turn: a role and its content."""

    role: str
    content: str


class WriteRequest(BaseModel):
    """Record one or more turns: append them to the short-term window synchronously; long-term
    extraction runs later, per fold, over the batch the appends evict.

    Turns are supplied either as a ``turns`` list (the batch shape the runtime uses to persist
    a whole interaction in one call) or as a single ``role``/``content`` pair (normalised into a
    one-element batch). ``infer`` controls whether the engine extracts facts (vs storing raw).
    ``failure_mode`` selects fail-soft (swallow long-term scheduling errors, return degraded) or
    strict (surface failures as an error); when omitted it inherits the service default.
    """

    scope: Scope
    turns: List[Turn] = Field(default_factory=list)
    role: Optional[str] = None
    content: Optional[str] = None
    infer: bool = True
    failure_mode: Optional[FailureMode] = None

    @model_validator(mode="after")
    def _normalise_turns(self) -> "WriteRequest":
        if self.role is not None and self.content is not None:
            self.turns = [Turn(role=self.role, content=self.content), *self.turns]
        if not self.turns:
            raise ValueError("write requires either turns[] or a role/content pair")
        return self


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
    failure_mode: Optional[FailureMode] = None


class ForgetResponse(BaseModel):
    """Acknowledges a forget. ``degraded`` is set when the long-term erasure failed
    under fail-soft (the short-term tier was still cleared)."""

    forgotten: bool = True
    degraded: bool = False


class ShortTermContext(BaseModel):
    """The short-term tier slice of a recall response: the verbatim active window."""

    recent: List[Tuple[str, str]] = Field(default_factory=list)


class MediumTermContext(BaseModel):
    """The medium-term tier slice of a recall response: the rolling conversation digest."""

    summary: str = ""


class RecallResponse(BaseModel):
    """Assembled recall context: native long-term facts, the medium-term digest, the
    short-term window, and a rendered block.

    ``facts`` are Mem0's native result dicts (memory text, score, id, metadata),
    passed through unmodified. ``medium_term`` carries the rolling digest and ``short_term``
    the verbatim recent turns. ``block`` is the deterministic structured text the runtime
    injects into the system context. ``degraded`` is set when long-term recall failed and
    only the conversational tiers are present.
    """

    facts: List[Dict[str, Any]] = Field(default_factory=list)
    short_term: ShortTermContext = Field(default_factory=ShortTermContext)
    medium_term: MediumTermContext = Field(default_factory=MediumTermContext)
    block: str = ""
    degraded: bool = False
