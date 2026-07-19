"""Entitlement-aware Pydantic AI memory toolset tests."""

from typing import Any, cast

import pytest
from pydantic_core import ValidationError

pytest.importorskip("pydantic_ai")

from kaos_memory.client import RecalledMemory
from kaos_memory.contract import ScopeLevel
from kaos_memory.pydantic_ai.toolset import MemoryToolset, SEARCH_MEMORY_TOOL


class _Memory:
    def __init__(self):
        self.recalls = []

    async def recall(self, scope, query):
        self.recalls.append((scope, query))
        return RecalledMemory()


class _Deps:
    def __init__(self):
        self.session_id = "session-1"
        self.security_context = {"principal": "alice", "actor": "request-agent"}
        self.memory = _Memory()


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


def _ctx(deps) -> Any:
    return cast(Any, _Ctx(deps))


@pytest.mark.asyncio
async def test_search_schema_enum_matches_entitlements_with_usage_help():
    toolset = MemoryToolset(
        [ScopeLevel.SESSION, ScopeLevel.USER, ScopeLevel.GROUP],
        expose_save=False,
    )
    tool = (await toolset.get_tools(_ctx(_Deps())))[SEARCH_MEMORY_TOOL]
    level = tool.tool_def.parameters_json_schema["properties"]["level"]

    assert level["enum"] == ["session", "user", "group"]
    assert "session = this conversation" in level["description"]
    assert "user = what is known about this user across agents" in level["description"]
    assert "group = knowledge shared across the group" in level["description"]


@pytest.mark.asyncio
async def test_single_entitlement_remains_a_required_one_value_enum():
    toolset = MemoryToolset([ScopeLevel.AGENT], expose_save=False)
    tool = (await toolset.get_tools(_ctx(_Deps())))[SEARCH_MEMORY_TOOL]
    schema = tool.tool_def.parameters_json_schema

    assert schema["properties"]["level"]["enum"] == ["agent"]
    assert schema["required"] == ["query", "level"]


@pytest.mark.asyncio
async def test_schema_rejects_out_of_enum_and_owner_arguments_before_handler():
    toolset = MemoryToolset([ScopeLevel.USER], expose_save=False)
    tool = (await toolset.get_tools(_ctx(_Deps())))[SEARCH_MEMORY_TOOL]

    with pytest.raises(ValidationError):
        tool.args_validator.validate_python({"query": "tea", "level": "group"})
    with pytest.raises(ValidationError):
        tool.args_validator.validate_python({"query": "tea"})
    with pytest.raises(ValidationError):
        tool.args_validator.validate_python(
            {"query": "tea", "level": "user", "principal": "mallory"}
        )


@pytest.mark.asyncio
async def test_handler_revalidates_entitlement():
    deps = _Deps()
    toolset = MemoryToolset([ScopeLevel.USER], expose_save=False)

    with pytest.raises(ValueError, match="not entitled"):
        await toolset.call_tool(
            SEARCH_MEMORY_TOOL,
            {"query": "tea", "level": "group"},
            _ctx(deps),
            cast(Any, None),
        )
    with pytest.raises(ValueError, match="not entitled"):
        await toolset.call_tool(
            SEARCH_MEMORY_TOOL,
            {"query": "tea"},
            _ctx(deps),
            cast(Any, None),
        )
    assert deps.memory.recalls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("level", list(ScopeLevel))
async def test_handler_derives_each_level_owner_from_server_dependencies(level):
    deps = _Deps()
    toolset = MemoryToolset(
        list(ScopeLevel),
        agent_identity="stable-agent",
        expose_save=False,
    )

    await toolset.call_tool(
        SEARCH_MEMORY_TOOL,
        {"query": "tea", "level": level.value},
        _ctx(deps),
        cast(Any, None),
    )

    scope, query = deps.memory.recalls[0]
    assert query == "tea"
    assert scope.level is level
    assert scope.principal == "alice"
    assert scope.agent_client_id == "stable-agent"
    assert scope.session_id == "session-1"
