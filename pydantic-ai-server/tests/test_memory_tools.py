"""Tests for the automatic-memory baseline and opt-in memory tools.

Cover which ``memory.tools`` settings expose which tools, that the toolset
registers only the enabled tools, and that save/search derive scope server-side
and operate over the memory backend without taking scope from the model.
"""

import pytest
from typing import Any, cast
from pydantic_ai.messages import ModelRequest, UserPromptPart

from pais.memory import MemoryScope, NullMemory, RecalledMemory, ScopeLevel
from pais.memory_tools import (
    MemoryTools,
    MemoryToolset,
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    build_memory_toolset,
    parse_memory_tools,
    tools_expose_save,
    tools_expose_search,
)
from pais.serverutils import AgentDeps
from tests.helpers import make_test_server


class _RecordingMemory(NullMemory):
    def __init__(self, recalled=None):
        super().__init__()
        self.writes = []
        self.recalls = []
        self._recalled = recalled or RecalledMemory()

    async def write(self, scope, turns, *, infer=True, failure_mode=None):
        self.writes.append((scope, turns, infer))
        return True

    async def recall(self, scope, query, **kwargs):
        self.recalls.append((scope, query))
        return self._recalled


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


def _ctx(deps) -> Any:
    return cast(Any, _Ctx(deps))


class TestMemoryToolsSelection:
    def test_parse_empty_is_none(self):
        assert parse_memory_tools("") is None

    def test_read_exposes_search_only(self):
        assert tools_expose_search(MemoryTools.READ)
        assert not tools_expose_save(MemoryTools.READ)

    def test_write_exposes_save_only(self):
        assert tools_expose_save(MemoryTools.WRITE)
        assert not tools_expose_search(MemoryTools.WRITE)

    def test_all_exposes_both(self):
        assert tools_expose_save(MemoryTools.ALL)
        assert tools_expose_search(MemoryTools.ALL)

    def test_none_exposes_neither(self):
        assert not tools_expose_save(None)
        assert not tools_expose_search(None)

    def test_build_toolset_returns_none_when_no_tools(self):
        assert build_memory_toolset(None, ScopeLevel.USER) is None

    def test_build_toolset_returns_toolset_when_tools_enabled(self):
        ts = build_memory_toolset(MemoryTools.ALL, ScopeLevel.USER, "agent-1")
        assert isinstance(ts, MemoryToolset)

    def test_build_toolset_read_registers_search_only(self):
        ts = build_memory_toolset(MemoryTools.READ, ScopeLevel.USER, "agent-1")
        assert ts is not None and ts._expose_search and not ts._expose_save

    def test_build_toolset_write_registers_save_only(self):
        ts = build_memory_toolset(MemoryTools.WRITE, ScopeLevel.USER, "agent-1")
        assert ts is not None and ts._expose_save and not ts._expose_search


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
        scope, turns, infer = mem.writes[0]
        assert isinstance(scope, MemoryScope)
        assert scope.level is ScopeLevel.USER
        assert scope.principal == "alice"
        assert scope.agent_client_id == "stable-id"
        assert turns == [("user", "alice likes tea")]

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
        deps = AgentDeps(
            session_id="s1",
            memory=mem,
            security_context={"principal": "a", "actor": "agent-a"},
        )
        ts = MemoryToolset(ScopeLevel.AGENT)
        result = await ts.call_tool(SEARCH_MEMORY_TOOL, {"query": "x"}, _ctx(deps), cast(Any, None))
        assert "fact one" in result

    @pytest.mark.asyncio
    async def test_search_handles_no_results(self):
        mem = _RecordingMemory(RecalledMemory())
        deps = AgentDeps(
            session_id="s1",
            memory=mem,
            security_context={"principal": "a", "actor": "agent-a"},
        )
        ts = MemoryToolset(ScopeLevel.AGENT)
        result = await ts.call_tool(SEARCH_MEMORY_TOOL, {"query": "x"}, _ctx(deps), cast(Any, None))
        assert "No relevant memories" in result

    @pytest.mark.asyncio
    async def test_tool_ignores_any_model_supplied_scope(self):
        # Even if the model passes scope-like args, they are ignored; scope comes
        # from deps + configured level only.
        mem = _RecordingMemory()
        deps = AgentDeps(
            session_id="s1",
            memory=mem,
            security_context={"principal": "alice", "actor": "agent-a"},
        )
        ts = MemoryToolset(ScopeLevel.AGENT)
        await ts.call_tool(
            SAVE_MEMORY_TOOL,
            {"content": "x", "scope": "group", "principal": "attacker"},
            _ctx(deps),
            cast(Any, None),
        )
        scope = mem.writes[0][0]
        assert scope.level is ScopeLevel.AGENT
        assert scope.principal == "alice"


@pytest.mark.asyncio
async def test_baseline_recall_uses_read_scope_and_flush_uses_home_scope():
    mem = _RecordingMemory()
    server = make_test_server(memory=mem)
    server.settings.memory_scope = "session"
    server.settings.memory_default_read_scope = "group"

    _prompt, _history, deps, _limits = await server._prepare_run("hello", "current-session")

    recalled_scope, query = mem.recalls[0]
    assert query == "hello"
    assert recalled_scope.level is ScopeLevel.GROUP
    assert recalled_scope.session_id == "current-session"
    assert deps.memory_scope is not None
    assert deps.memory_scope.level is ScopeLevel.SESSION
    assert deps.memory_scope.session_id == "current-session"

    await server._write_turns(
        deps,
        [ModelRequest(parts=[UserPromptPart(content="hello")])],
    )
    written_scope = mem.writes[0][0]
    assert written_scope.level is ScopeLevel.SESSION
    assert written_scope.session_id == "current-session"
