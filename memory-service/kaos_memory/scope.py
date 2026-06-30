"""Scope value object and its translation to Mem0 owner identifiers.

A ``Scope`` names *whose* memory an operation touches. KAOS exposes three scope
levels on an agent plus implicit session isolation; each maps onto one of Mem0's
owner identifiers (``user_id`` / ``agent_id`` / ``run_id``) that the vector store
pre-filters on inside the query.

This module ships only the data shape and a correct translation. Non-optional,
fail-closed *enforcement* (rejecting under-specified scopes, A2A prefix
inheritance, erasure fan-out) lands in a later phase; here a scope is simply
mapped to the right Mem0 keyword arguments.

Note: Mem0 2.x rejects a search whose filters carry none of
``user_id``/``agent_id``/``run_id``. The ``shared`` level therefore maps to a
*reserved shared owner id* (never an empty filter) so a store-wide shared
namespace is addressable without colliding with any real agent or principal.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, model_validator

#: Reserved owner id naming the store-wide shared namespace. It is mapped onto
#: ``agent_id`` and is deliberately distinct from any real agent client id, so a
#: ``shared`` operation never collides with a ``private`` (per-agent) one.
SHARED_OWNER = "kaos:shared"


class ScopeLevel(str, Enum):
    """The memory scope an operation targets.

    - ``PRIVATE``: only this agent (mapped to ``agent_id``).
    - ``USER``: all agents acting for a principal (mapped to ``user_id``).
    - ``SHARED``: every agent on the store (mapped to the reserved shared owner).
    - ``SESSION``: a single run/conversation (mapped to ``run_id``).
    """

    PRIVATE = "private"
    USER = "user"
    SHARED = "shared"
    SESSION = "session"


class Scope(BaseModel):
    """Identifies the owner of a memory operation.

    Carries the principal, the agent's stable client id, and the session id, plus
    the selected ``level``. Only the field required by ``level`` must be present;
    the rest may be unset (an under-specified scope is representable here and is
    rejected by enforcement later, not by construction).
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
        if self.level is ScopeLevel.PRIVATE:
            return self.agent_client_id is not None
        if self.level is ScopeLevel.USER:
            return self.principal is not None
        if self.level is ScopeLevel.SESSION:
            return self.session_id is not None
        return True  # SHARED always resolves to the reserved owner.

    def owner_kwargs(self) -> Dict[str, Any]:
        """Return the Mem0 owner keyword arguments for a write/search at this scope.

        Exactly one of ``user_id`` / ``agent_id`` / ``run_id`` is set. Raises if the
        field required by ``level`` is missing, so an unusable scope never silently
        widens to another owner.
        """
        if self.level is ScopeLevel.PRIVATE:
            if self.agent_client_id is None:
                raise ValueError("private scope requires agent_client_id")
            return {"agent_id": self.agent_client_id}
        if self.level is ScopeLevel.USER:
            if self.principal is None:
                raise ValueError("user scope requires principal")
            return {"user_id": self.principal}
        if self.level is ScopeLevel.SESSION:
            if self.session_id is None:
                raise ValueError("session scope requires session_id")
            return {"run_id": self.session_id}
        return {"agent_id": SHARED_OWNER}

    def search_filters(self) -> Dict[str, Any]:
        """Return the Mem0 ``filters`` dict for a search at this scope.

        Identical to the owner kwargs: Mem0 2.x uses the same owner keys inside the
        ``filters`` argument and requires at least one of them, which this always
        provides.
        """
        return self.owner_kwargs()
