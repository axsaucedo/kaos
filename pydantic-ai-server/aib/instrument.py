"""AIB propagation SDK — request-local security context and header propagation.

This module carries two identities across agent hops:

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
import os
import uuid
from typing import Any, Callable, Dict, Iterator, MutableMapping, Optional

# --- Header model -----------------------------------------------------
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


#: Context fields safe to expose to application code / persist (no raw bearer tokens).
_NON_SECRET_FIELDS = ("request_id", "session_id", "principal", "actor", "scopes")


def security_context() -> Dict[str, Any]:
    """Return the non-secret subset of the current context.

    Excludes raw bearer tokens (``subject_token``/``actor_token``) so the result is safe
    to expose to tools or persist for audit/correlation.
    """
    data = _ctx_var.get()
    return {key: data[key] for key in _NON_SECRET_FIELDS if data.get(key)}


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


# --- Inbound boundary instrumentation -----------------------------------------------

# Inbound header an upstream/UI uses to carry the session when AIB's own is absent.
_LEGACY_SESSION_HEADER = "x-session-id"

# Resolver derives the verified user principal from inbound headers (e.g. gateway-set).
PrincipalResolver = Callable[[Dict[str, str]], Optional[str]]


def _strip_bearer(value: Optional[str]) -> Optional[str]:
    """Return the raw token from an ``Authorization: Bearer <token>`` value."""
    if value and value.lower().startswith("bearer "):
        return value[7:]
    return value


def _scope_headers(scope: Dict[str, Any]) -> Dict[str, str]:
    """Lower-cased header map from an ASGI scope (last value wins)."""
    headers: Dict[str, str] = {}
    for raw_key, raw_value in scope.get("headers", []):
        headers[raw_key.decode("latin-1").lower()] = raw_value.decode("latin-1")
    return headers


def _extract_inbound(
    headers: Dict[str, str],
    *,
    actor: Optional[str],
    actor_token: Optional[str],
    principal_resolver: Optional[PrincipalResolver],
    default_principal: Optional[str],
) -> Dict[str, Any]:
    """Build the request context from trusted inbound headers + local defaults.

    The user **subject** (principal + token) is taken from the inbound request and
    propagated unchanged. The **actor** (this agent's own identity/token) is always the
    *local* value, never the inbound caller's actor — so each hop authenticates as
    itself. A ``request_id`` is generated when the caller does not supply one.
    """
    request_id = headers.get(HEADER_REQUEST_ID) or f"req-{uuid.uuid4().hex[:16]}"
    session_id = headers.get(HEADER_SESSION_ID) or headers.get(_LEGACY_SESSION_HEADER)

    principal = headers.get(HEADER_PRINCIPAL)
    if not principal and principal_resolver is not None:
        principal = principal_resolver(headers)
    if not principal:
        principal = default_principal

    return _build_context(
        request_id=request_id,
        session_id=session_id,
        principal=principal,
        subject_token=_strip_bearer(headers.get(HEADER_SUBJECT_TOKEN)),
        scopes=headers.get(HEADER_SCOPES),
        actor=actor,
        actor_token=actor_token,
    )


class _PropagationMiddleware:
    """Pure ASGI middleware that initializes :data:`ctx` per request.

    A pure ASGI middleware (rather than ``BaseHTTPMiddleware``) runs the downstream app
    in the *same* task, so the ``ContextVar`` set here is visible to the endpoint and to
    every outbound call it makes.
    """

    def __init__(
        self,
        app: Any,
        *,
        actor: Optional[str],
        actor_token: Optional[str],
        principal_resolver: Optional[PrincipalResolver],
        default_principal: Optional[str],
    ) -> None:
        self.app = app
        self._actor = actor
        self._actor_token = actor_token
        self._principal_resolver = principal_resolver
        self._default_principal = default_principal

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        context = _extract_inbound(
            _scope_headers(scope),
            actor=self._actor,
            actor_token=self._actor_token,
            principal_resolver=self._principal_resolver,
            default_principal=self._default_principal,
        )
        token = ctx.replace(context)
        try:
            await self.app(scope, receive, send)
        finally:
            ctx.reset(token)


def instrument_fastapi(
    app: Any,
    *,
    actor: Optional[str] = None,
    actor_token: Optional[str] = None,
    principal: Optional[str] = None,
    principal_resolver: Optional[PrincipalResolver] = None,
) -> Any:
    """Instrument a FastAPI/Starlette app to populate :data:`ctx` per request.

    Local runtime identity (``actor``/``actor_token``/``principal``) falls back to the
    ``AIB_ACTOR`` / ``AIB_ACTOR_TOKEN`` / ``AIB_PRINCIPAL`` environment variables. The
    user principal is normally taken from the inbound ``x-principal`` header or the
    ``principal_resolver``; the fixed ``principal`` is only a fallback for processes with
    a constant trusted principal.
    """
    app.add_middleware(
        _PropagationMiddleware,
        actor=actor or os.environ.get("AIB_ACTOR"),
        actor_token=actor_token or os.environ.get("AIB_ACTOR_TOKEN"),
        principal_resolver=principal_resolver,
        default_principal=principal or os.environ.get("AIB_PRINCIPAL"),
    )
    return app


# --- Outbound injection instrumentation ---------------------------------------------

_httpx_patched = False


def _inject_request_headers(request: Any) -> None:
    """Merge the current context's propagation headers into an outbound request.

    Strictly **additive**: a header already present on the request (for example the
    ModelAPI/LLM provider's own ``Authorization`` API key) is never overwritten.
    """
    for header, value in ctx.to_headers().items():
        if header not in request.headers:
            request.headers[header] = value


def instrument_httpx() -> None:
    """Patch ``httpx`` so outbound requests carry the propagation headers.

    Both ``httpx.Client`` and ``httpx.AsyncClient`` route ``get``/``post``/``request``
    through ``send``, so patching ``send`` covers every transport — A2A, MCP, and
    ModelAPI clients alike — and injection happens at request time, so clients built once
    at startup still propagate per-request context. Idempotent.

    Injection is additive and reads from :data:`ctx`; in internet-facing deployments,
    callers are responsible for not placing sensitive tokens in :data:`ctx` for requests
    bound to untrusted destinations.
    """
    global _httpx_patched
    if _httpx_patched:
        return

    import httpx

    sync_send = httpx.Client.send
    async_send = httpx.AsyncClient.send

    def _patched_sync_send(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        _inject_request_headers(request)
        return sync_send(self, request, *args, **kwargs)

    async def _patched_async_send(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        _inject_request_headers(request)
        return await async_send(self, request, *args, **kwargs)

    httpx.Client.send = _patched_sync_send  # ty: ignore[invalid-assignment]
    httpx.AsyncClient.send = _patched_async_send  # ty: ignore[invalid-assignment]
    _httpx_patched = True
