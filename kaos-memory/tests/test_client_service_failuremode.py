"""Cross-component verification of the failure-mode contract over real HTTP.

These tests wire the :class:`MemoryServiceClient` (the same client the agent
runtime delegates to) to a real service app through an in-process ASGI
transport, so the soft/strict behaviour is exercised across the client-service
boundary rather than in isolation. They prove three guarantees end to end:

- recall is always best-effort: a long-term backend failure degrades to an
  empty-facts result while the verbatim short-term window survives;
- a ``soft`` write tolerates a service-side failure: the service degrades the
  response instead of erroring, so the client returns without raising;
- a ``strict`` write surfaces the service error as a raised exception.
"""

import httpx
import pytest

from kaos_memory.app import MemoryService, create_app
from kaos_memory.client import MemoryServiceClient
from kaos_memory.config import ShortTermTierConfig
from kaos_memory.contract import Scope, ScopeLevel
from kaos_memory.stores import ShortTermStore

USER_SCOPE = Scope(level=ScopeLevel.USER, principal="alice", session_id="session-1")


class _FakeLongTerm:
    """Long-term stand-in whose recall/add either succeed or raise on demand."""

    def __init__(self, facts=None, fail=False):
        self._facts = facts or []
        self._fail = fail

    def recall(self, scope, query, top_k=10):
        if self._fail:
            raise RuntimeError("vector store unreachable")
        return self._facts

    def add(self, scope, messages, infer=True):
        if self._fail:
            raise RuntimeError("vector store unreachable")
        return []

    def ping(self):
        return None


class _FailingShortTerm:
    """Short-term stand-in whose append fails, to drive a service-side write error."""

    def add(self, scope, turns):
        raise RuntimeError("short-term storage unavailable")

    def summary(self, scope):
        return ""

    def active_window(self, scope, token_budget=None):
        return []

    def clear(self, scope):
        return None

    def ping(self):
        return None


def _short_term(tmp_path):
    return ShortTermStore("local", str(tmp_path / "w.db"), ShortTermTierConfig(), lambda p, f: p)


def _app(longterm, short_term):
    """Build the service app from stores (untyped so test doubles are accepted)."""
    return create_app(MemoryService(longterm=longterm, short_term=short_term))


def _client_over(app):
    """Bind a MemoryServiceClient to an app through an in-process ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://memory.svc")
    return MemoryServiceClient("http://memory.svc", client=http)


@pytest.mark.asyncio
async def test_recall_degrades_over_http_when_longterm_fails(tmp_path):
    short_term = _short_term(tmp_path)
    short_term.add(USER_SCOPE, [("user", "the budget is 5000")])
    app = _app(_FakeLongTerm(fail=True), short_term)

    client = _client_over(app)
    try:
        recalled = await client.recall(USER_SCOPE, "budget")
    finally:
        await client.close()

    # Long-term failure degrades the result, but the request succeeds and the
    # verbatim short-term window still comes back for replay.
    assert recalled.degraded is True
    assert recalled.facts == []
    assert ("user", "the budget is 5000") in recalled.short_term.recent


@pytest.mark.asyncio
async def test_soft_write_tolerates_service_failure_over_http(tmp_path):
    app = _app(_FakeLongTerm(), _FailingShortTerm())

    client = _client_over(app)
    try:
        accepted = await client.write(USER_SCOPE, [("user", "hello")], failure_mode="soft")
    finally:
        await client.close()

    # A soft write does not raise: the service degrades the append internally and
    # still acknowledges the request rather than surfacing a 500 to the caller.
    assert accepted is True


@pytest.mark.asyncio
async def test_strict_write_surfaces_service_failure_over_http(tmp_path):
    app = _app(_FakeLongTerm(), _FailingShortTerm())

    client = _client_over(app)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.write(USER_SCOPE, [("user", "hello")], failure_mode="strict")
    finally:
        await client.close()
