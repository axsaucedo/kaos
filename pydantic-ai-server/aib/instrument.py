"""AIB propagation SDK — request-local security context and header propagation.

This module is the propagation slice of the AIB Python SDK (ADR-AIB-001 /
ADR-KAOS-003). It carries two identities across agent hops:

* the user **subject** (principal + ``Authorization`` bearer), propagated unchanged, and
* the calling agent **actor** (the local agent's own identity + ``x-agent-authorization``
  bearer), set to *this* workload on every outbound hop so each agent authenticates as
  itself.

It is intentionally small: a ``ContextVar``-backed request-local mapping (:data:`ctx`),
a header serializer (:meth:`_Context.to_headers`), and the inbound/outbound instrumentation
(added in sibling commits). The SDK is *not* the enforcement boundary — it only propagates.
"""

from __future__ import annotations

import contextvars
from typing import Any, Dict, Iterator, MutableMapping, Optional

# --- Header model (ADR-AIB-001) -----------------------------------------------------
# Generic headers for concepts not owned by AIB; ``x-aib-*`` reserved for AIB-owned context.
HEADER_REQUEST_ID = "x-request-id"
HEADER_SESSION_ID = "x-aib-session-id"
HEADER_PRINCIPAL = "x-principal"
HEADER_ACTOR = "x-actor"
HEADER_SCOPES = "x-aib-scopes"
HEADER_SUBJECT_TOKEN = "authorization"
HEADER_ACTOR_TOKEN = "x-agent-authorization"

# Context keys carrying a raw bearer token; serialized as ``Bearer <value>`` and never logged.
_TOKEN_FIELDS = {"subject_token": HEADER_SUBJECT_TOKEN, "actor_token": HEADER_ACTOR_TOKEN}

# Context keys carrying plain identifiers/correlation values.
_PLAIN_FIELDS = {
    "request_id": HEADER_REQUEST_ID,
    "session_id": HEADER_SESSION_ID,
    "principal": HEADER_PRINCIPAL,
    "actor": HEADER_ACTOR,
    "scopes": HEADER_SCOPES,
}


def _as_bearer(value: str) -> str:
    """Wrap a raw token as a ``Bearer`` credential unless it already is one."""
    if value.lower().startswith("bearer "):
        return value
    return f"Bearer {value}"


class _Context(MutableMapping[str, Any]):
    """Dict-like view over a request-local ``ContextVar`` mapping.

    Mutations target the current context only, so concurrent requests (each running in
    their own ``ContextVar`` context) never see each other's identity.
    """

    def __init__(self, var: "contextvars.ContextVar[Dict[str, Any]]") -> None:
        self._var = var

    def _data(self) -> Dict[str, Any]:
        return self._var.get()

    def __getitem__(self, key: str) -> Any:
        return self._data()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        data = dict(self._data())
        data[key] = value
        self._var.set(data)

    def __delitem__(self, key: str) -> None:
        data = dict(self._data())
        del data[key]
        self._var.set(data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def replace(self, values: Dict[str, Any]) -> "contextvars.Token[Dict[str, Any]]":
        """Replace the whole mapping, returning a token for :meth:`reset`."""
        return self._var.set(dict(values))

    def reset(self, token: "contextvars.Token[Dict[str, Any]]") -> None:
        """Restore the mapping captured before a :meth:`replace`."""
        self._var.reset(token)

    def to_headers(self) -> Dict[str, str]:
        """Serialize the current context into outbound propagation headers.

        Only non-empty fields are emitted. Token fields are ``Bearer``-wrapped. The
        result is intended to be merged *additively* into an outbound request (callers
        must not overwrite headers a user already set).
        """
        data = self._data()
        headers: Dict[str, str] = {}
        for field, header in _PLAIN_FIELDS.items():
            value = data.get(field)
            if value:
                headers[header] = str(value)
        for field, header in _TOKEN_FIELDS.items():
            value = data.get(field)
            if value:
                headers[header] = _as_bearer(str(value))
        return headers


_ctx_var: "contextvars.ContextVar[Dict[str, Any]]" = contextvars.ContextVar("aib_ctx", default={})

#: Request-local security context (``ContextVar``-backed, dict-like).
ctx = _Context(_ctx_var)


def current() -> Dict[str, Any]:
    """Return a shallow copy of the current context mapping."""
    return dict(_ctx_var.get())


def to_headers() -> Dict[str, str]:
    """Module-level convenience for :meth:`ctx.to_headers`."""
    return ctx.to_headers()


def _build_context(
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    principal: Optional[str] = None,
    subject_token: Optional[str] = None,
    actor: Optional[str] = None,
    actor_token: Optional[str] = None,
    scopes: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a context mapping from explicit fields, dropping empties."""
    fields = {
        "request_id": request_id,
        "session_id": session_id,
        "principal": principal,
        "subject_token": subject_token,
        "actor": actor,
        "actor_token": actor_token,
        "scopes": scopes,
    }
    return {key: value for key, value in fields.items() if value}
