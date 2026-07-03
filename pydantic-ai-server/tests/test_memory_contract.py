"""Tests for the tiered memory contract: scope value objects, recall/write/forget.

These cover the long-term tier surface added to the ``Memory`` interface. The
default implementations are no-ops appropriate for short-term-only and disabled
backends; the service-backed implementation that overrides them is covered
separately.
"""

import pytest

from pais.memory import (
    LocalMemory,
    Memory,
    MemoryScope,
    NullMemory,
    RecalledMemory,
    ScopeLevel,
)


class TestMemoryScope:
    def test_scope_payload_round_trips_fields(self):
        scope = MemoryScope(
            level=ScopeLevel.USER,
            principal="alice",
            agent_client_id="agent-1",
            session_id="sess-1",
        )
        payload = scope.to_payload()
        assert payload == {
            "level": "user",
            "principal": "alice",
            "agent_client_id": "agent-1",
            "session_id": "sess-1",
        }

    def test_scope_level_values(self):
        assert ScopeLevel.PRIVATE.value == "private"
        assert ScopeLevel.USER.value == "user"
        assert ScopeLevel.SHARED.value == "shared"
        assert ScopeLevel.SESSION.value == "session"

    def test_under_specified_scope_is_representable(self):
        scope = MemoryScope(level=ScopeLevel.SHARED)
        assert scope.principal is None
        assert scope.to_payload()["level"] == "shared"


class TestRecalledMemory:
    def test_empty_by_default(self):
        recalled = RecalledMemory()
        assert recalled.is_empty
        assert recalled.facts == []
        assert recalled.recent == []
        assert recalled.block == ""
        assert recalled.degraded is False

    def test_non_empty_when_facts_present(self):
        recalled = RecalledMemory(facts=[{"memory": "x"}])
        assert not recalled.is_empty

    def test_non_empty_when_short_term_present(self):
        recalled = RecalledMemory(recent=[("user", "hi")])
        assert not recalled.is_empty


class TestLongTermDefaultsAreNoOp:
    @pytest.mark.asyncio
    async def test_local_memory_recall_is_empty(self):
        scope = MemoryScope(level=ScopeLevel.SESSION, session_id="s1")
        recalled = await LocalMemory().recall(scope, "anything")
        assert isinstance(recalled, RecalledMemory)
        assert recalled.is_empty

    @pytest.mark.asyncio
    async def test_local_memory_write_accepts(self):
        scope = MemoryScope(level=ScopeLevel.SESSION, session_id="s1")
        assert await LocalMemory().write(scope, [("user", "hello")]) is True

    @pytest.mark.asyncio
    async def test_local_memory_forget_accepts(self):
        scope = MemoryScope(level=ScopeLevel.SESSION, session_id="s1")
        assert await LocalMemory().forget(scope) is True

    @pytest.mark.asyncio
    async def test_null_memory_long_term_noop(self):
        scope = MemoryScope(level=ScopeLevel.PRIVATE, agent_client_id="a1")
        mem = NullMemory()
        assert (await mem.recall(scope, "q")).is_empty
        assert await mem.write(scope, [("user", "hi")]) is True
        assert await mem.forget(scope) is True

    def test_long_term_methods_are_on_the_base_interface(self):
        assert hasattr(Memory, "recall")
        assert hasattr(Memory, "write")
        assert hasattr(Memory, "forget")
