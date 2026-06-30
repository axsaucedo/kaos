"""Tests for recall presentation: block gating and opt-in memory tools.

Cover which presentation modes inject the block and expose tools, that the
toolset registers only the enabled tools, and that save/search derive scope
server-side and operate over the memory backend without taking scope from the
model.
"""

import pytest
from typing import Any, cast

from pais.memory import MemoryScope, NullMemory, RecalledMemory, ScopeLevel
from pais.memory_tools import (
    MemoryToolset,
    RecallPresentation,
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    build_memory_toolset,
    presentation_exposes_tools,
    presentation_injects_block,
)
from pais.serverutils import AgentDeps


class _RecordingMemory(NullMemory):
    def __init__(self, recalled=None):
        super().__init__()
        self.writes = []
        self.recalls = []
        self._recalled = recalled or RecalledMemory()

    async def write(self, scope, role, content, *, infer=True, failure_mode="soft"):
        self.writes.append((scope, role, content, infer))
        return True

    async def recall(self, scope, query, **kwargs):
        self.recalls.append((scope, query))
        return self._recalled


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


def _ctx(deps) -> Any:
    return cast(Any, _Ctx(deps))


class TestPresentationGating:
    def test_block_mode_injects_block_only(self):
        assert presentation_injects_block(RecallPresentation.BLOCK)
        assert not presentation_exposes_tools(RecallPresentation.BLOCK)

    def test_tools_mode_exposes_tools_only(self):
        assert not presentation_injects_block(RecallPresentation.TOOLS)
        assert presentation_exposes_tools(RecallPresentation.TOOLS)

    def test_both_mode_does_both(self):
        assert presentation_injects_block(RecallPresentation.BOTH)
        assert presentation_exposes_tools(RecallPresentation.BOTH)

    def test_build_toolset_returns_none_for_block_mode(self):
        assert build_memory_toolset(RecallPresentation.BLOCK, ScopeLevel.USER) is None

    def test_build_toolset_returns_toolset_when_tools_enabled(self):
        ts = build_memory_toolset(RecallPresentation.BOTH, ScopeLevel.USER, "agent-1")
        assert isinstance(ts, MemoryToolset)


class TestMemoryToolset:
    @pytest.mark.asyncio
    async def test_registers_both_tools_by_default(self):
        ts = MemoryToolset(ScopeLevel.USER)
        tools = await ts.get_tools(_ctx(AgentDeps(session_id="s1", memory=_RecordingMemory())))
        assert set(tools) == {SAVE_MEMORY_TOOL, SEARCH_MEMORY_TOOL}

    @pytest.mark.asyncio
    async def test_can_expose_only_search(self):
        ts = MemoryToolset(ScopeLevel.USER, expose_save=False)
        tools = await ts.get_tools(_ctx(AgentDeps(session_id="s1", memory=_RecordingMemory())))
        assert set(tools) == {SEARCH_MEMORY_TOOL}

    @pytest.mark.asyncio
    async def test_save_derives_scope_server_side_and_writes(self):
        mem = _RecordingMemory()
        deps = AgentDeps(
            session_id="s1",
            memory=mem,
            security_context={"principal": "alice", "actor": "agent-actor"},
        )
        ts = MemoryToolset(ScopeLevel.USER, agent_identity="stable-id")
        result = await ts.call_tool(
            SAVE_MEMORY_TOOL, {"content": "alice likes tea"}, _ctx(deps), cast(Any, None)
        )
        assert "Saved" in result
        scope, role, content, infer = mem.writes[0]
        assert isinstance(scope, MemoryScope)
        assert scope.level is ScopeLevel.USER
        assert scope.principal == "alice"
        assert scope.agent_client_id == "stable-id"
        assert content == "alice likes tea"

    @pytest.mark.asyncio
    async def test_search_returns_block_when_present(self):
        mem = _RecordingMemory(RecalledMemory(block="## Relevant memory\nalice likes tea"))
        deps = AgentDeps(session_id="s1", memory=mem, security_context={"principal": "alice"})
        ts = MemoryToolset(ScopeLevel.USER)
        result = await ts.call_tool(
            SEARCH_MEMORY_TOOL, {"query": "tea"}, _ctx(deps), cast(Any, None)
        )
        assert "alice likes tea" in result
        assert mem.recalls[0][1] == "tea"

    @pytest.mark.asyncio
    async def test_search_falls_back_to_facts(self):
        mem = _RecordingMemory(RecalledMemory(facts=[{"memory": "fact one"}]))
        deps = AgentDeps(session_id="s1", memory=mem, security_context={"principal": "a"})
        ts = MemoryToolset(ScopeLevel.PRIVATE)
        result = await ts.call_tool(SEARCH_MEMORY_TOOL, {"query": "x"}, _ctx(deps), cast(Any, None))
        assert "fact one" in result

    @pytest.mark.asyncio
    async def test_search_handles_no_results(self):
        mem = _RecordingMemory(RecalledMemory())
        deps = AgentDeps(session_id="s1", memory=mem, security_context={"principal": "a"})
        ts = MemoryToolset(ScopeLevel.PRIVATE)
        result = await ts.call_tool(SEARCH_MEMORY_TOOL, {"query": "x"}, _ctx(deps), cast(Any, None))
        assert "No relevant memories" in result

    @pytest.mark.asyncio
    async def test_tool_ignores_any_model_supplied_scope(self):
        # Even if the model passes scope-like args, they are ignored; scope comes
        # from deps + configured level only.
        mem = _RecordingMemory()
        deps = AgentDeps(session_id="s1", memory=mem, security_context={"principal": "alice"})
        ts = MemoryToolset(ScopeLevel.PRIVATE)
        await ts.call_tool(
            SAVE_MEMORY_TOOL,
            {"content": "x", "scope": "shared", "principal": "attacker"},
            _ctx(deps),
            cast(Any, None),
        )
        scope = mem.writes[0][0]
        assert scope.level is ScopeLevel.PRIVATE
        assert scope.principal == "alice"
