"""Agent identity and request-context propagation runtime.

Two-identity request-context propagation for agentic runtimes. Instrument once and the
user subject + agent actor identities flow across A2A, MCP, and ModelAPI calls
automatically.

Public API::

    import kaos_identity

    kaos_identity.ctx                      # request-local context (ContextVar-backed, dict-like)
    kaos_identity.instrument_fastapi(app)  # extract trusted inbound context at the server boundary
    kaos_identity.instrument_httpx()       # inject subject + actor on outbound httpx calls
    kaos_identity.ctx.to_headers()         # manual escape hatch for non-instrumented transports

The SDK is *not* the enforcement boundary; it only propagates.
"""

from __future__ import annotations

from .client import (
    AccessDecision,
    AccessDenied,
    AccessRequest,
    AsyncClient,
    Client,
    ReauthenticationRequired,
    TokenResult,
    outcome_from_response,
    raise_for_gateway_outcome,
)
from .identity import (
    IdentityUnavailable,
    ActorTokenManager,
    actor_token,
    actor_token_async,
    get_manager,
    instrument_agent_identity,
    reset_manager,
)
from .instrument import (
    HEADER_ACCESS_REASON,
    HEADER_ACTOR,
    HEADER_ACTOR_TOKEN,
    HEADER_PRINCIPAL,
    HEADER_REAUTH_URL,
    HEADER_REQUEST_ID,
    HEADER_SCOPES,
    HEADER_SESSION_ID,
    HEADER_SUBJECT_TOKEN,
    autonomous_identity_context,
    ctx,
    current,
    instrument_fastapi,
    instrument_httpx,
    security_context,
    to_headers,
)

__all__ = [
    "ctx",
    "current",
    "security_context",
    "to_headers",
    "autonomous_identity_context",
    "instrument_fastapi",
    "instrument_httpx",
    "instrument_agent_identity",
    "actor_token",
    "actor_token_async",
    "get_manager",
    "reset_manager",
    "ActorTokenManager",
    "IdentityUnavailable",
    "Client",
    "AsyncClient",
    "AccessRequest",
    "AccessDecision",
    "AccessDenied",
    "ReauthenticationRequired",
    "TokenResult",
    "outcome_from_response",
    "raise_for_gateway_outcome",
    "HEADER_REQUEST_ID",
    "HEADER_SESSION_ID",
    "HEADER_PRINCIPAL",
    "HEADER_ACTOR",
    "HEADER_SCOPES",
    "HEADER_SUBJECT_TOKEN",
    "HEADER_ACTOR_TOKEN",
    "HEADER_ACCESS_REASON",
    "HEADER_REAUTH_URL",
]
