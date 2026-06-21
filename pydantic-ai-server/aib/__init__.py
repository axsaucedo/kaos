"""AIB propagation SDK (KAOS temporary home).

Two-identity request-context propagation for agentic runtimes — the propagation slice of
ADR-AIB-001 / ADR-KAOS-003. Instrument once and the user subject + agent actor identities
flow across A2A, MCP, and ModelAPI calls automatically.

Public API::

    import aib

    aib.ctx                      # request-local context (ContextVar-backed, dict-like)
    aib.instrument_fastapi(app)  # extract trusted inbound context at the server boundary
    aib.instrument_httpx()       # inject subject + actor on outbound httpx calls
    aib.ctx.to_headers()         # manual escape hatch for non-instrumented transports

The SDK is *not* the enforcement boundary; it only propagates.
"""

from __future__ import annotations

from .instrument import (
    HEADER_ACTOR,
    HEADER_ACTOR_TOKEN,
    HEADER_PRINCIPAL,
    HEADER_REQUEST_ID,
    HEADER_SCOPES,
    HEADER_SESSION_ID,
    HEADER_SUBJECT_TOKEN,
    ctx,
    current,
    instrument_fastapi,
    to_headers,
)

__all__ = [
    "ctx",
    "current",
    "to_headers",
    "instrument_fastapi",
    "HEADER_REQUEST_ID",
    "HEADER_SESSION_ID",
    "HEADER_PRINCIPAL",
    "HEADER_ACTOR",
    "HEADER_SCOPES",
    "HEADER_SUBJECT_TOKEN",
    "HEADER_ACTOR_TOKEN",
]
