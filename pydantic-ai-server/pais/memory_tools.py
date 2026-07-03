"""Opt-in agent memory tools and automatic-memory layering.

When memory is enabled the runtime always applies the automatic baseline: it
recalls relevant memory and injects it as a context block before the run, and
flushes the run's turns for extraction afterwards. On top of that baseline,
``memory.tools`` optionally exposes explicit agent-driven tools:

- ``read``: expose ``search_memory`` (the agent retrieves on demand).
- ``write``: expose ``save_memory`` (the agent saves on demand).
- ``all``: expose both.
- unset: no explicit tools (pure automatic).

The tools never accept a scope from the model. The scope is derived server-side
from the run dependencies and the agent's configured level/identity, so a tool
call can only ever touch the memory the agent is entitled to.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional, TYPE_CHECKING

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator, core_schema

from pais.memory import ScopeLevel, scope_from_deps

if TYPE_CHECKING:
    from pais.serverutils import AgentDeps

logger = logging.getLogger(__name__)

SAVE_MEMORY_TOOL = "save_memory"
SEARCH_MEMORY_TOOL = "search_memory"

_SAVE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": "A durable fact or preference to remember for future conversations.",
        }
    },
    "required": ["content"],
}
_SEARCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "What to look up in long-term memory.",
        }
    },
    "required": ["query"],
}
_VALIDATOR = SchemaValidator(schema=core_schema.any_schema())


class MemoryTools(str, Enum):
    """Which explicit memory tools an agent is given, on top of automatic memory.

    Memory, when enabled, always recalls-and-injects before a run and flushes-and-
    extracts after it (the automatic baseline). This selects the *additional*
    agent-driven tools layered on top:

    - ``READ``: expose ``search_memory`` (on-demand retrieval).
    - ``WRITE``: expose ``save_memory`` (on-demand save).
    - ``ALL``: expose both.
    """

    ALL = "all"
    READ = "read"
    WRITE = "write"


def tools_expose_save(tools: Optional["MemoryTools"]) -> bool:
    """True when ``save_memory`` should be registered."""
    return tools in (MemoryTools.ALL, MemoryTools.WRITE)


def tools_expose_search(tools: Optional["MemoryTools"]) -> bool:
    """True when ``search_memory`` should be registered."""
    return tools in (MemoryTools.ALL, MemoryTools.READ)


class MemoryToolset(AbstractToolset["AgentDeps"]):
    """Exposes opt-in ``save_memory`` / ``search_memory`` tools over the memory backend.

    Scope is derived server-side per call from the run dependencies and the
    agent's configured level/identity; the model only supplies the content to save
    or the query to search.
    """

    def __init__(
        self,
        scope_level: ScopeLevel,
        agent_identity: Optional[str] = None,
        *,
        expose_save: bool = True,
        expose_search: bool = True,
    ):
        self._level = scope_level
        self._identity = agent_identity
        self._expose_save = expose_save
        self._expose_search = expose_search

    @property
    def id(self) -> str:
        return "kaos-memory"

    async def get_tools(self, ctx: RunContext["AgentDeps"]) -> dict[str, ToolsetTool["AgentDeps"]]:
        tools: dict[str, ToolsetTool["AgentDeps"]] = {}
        if self._expose_save:
            tools[SAVE_MEMORY_TOOL] = ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=SAVE_MEMORY_TOOL,
                    description=(
                        "Save a durable fact or user preference to long-term memory so it "
                        "can be recalled in future conversations."
                    ),
                    parameters_json_schema=_SAVE_SCHEMA,
                ),
                max_retries=0,
                args_validator=_VALIDATOR,
            )
        if self._expose_search:
            tools[SEARCH_MEMORY_TOOL] = ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=SEARCH_MEMORY_TOOL,
                    description="Search long-term memory for facts relevant to a query.",
                    parameters_json_schema=_SEARCH_SCHEMA,
                ),
                max_retries=0,
                args_validator=_VALIDATOR,
            )
        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext["AgentDeps"],
        tool: ToolsetTool["AgentDeps"],
    ) -> str:
        memory = ctx.deps.memory
        if memory is None:
            return "Memory is not available."
        scope = scope_from_deps(ctx.deps, level=self._level, agent_identity=self._identity)

        if name == SAVE_MEMORY_TOOL:
            content = str(tool_args.get("content", "")).strip()
            if not content:
                return "Nothing to save."
            ok = await memory.write(scope, [("user", content)], infer=True)
            return "Saved to long-term memory." if ok else "Could not save to memory right now."

        if name == SEARCH_MEMORY_TOOL:
            query = str(tool_args.get("query", "")).strip()
            if not query:
                return "No query provided."
            recalled = await memory.recall(scope, query)
            if recalled.block:
                return recalled.block
            if recalled.facts:
                return "\n".join(str(fact.get("memory", fact)) for fact in recalled.facts)
            return "No relevant memories found."

        return f"Unknown memory tool: {name}"


def parse_memory_tools(value: str) -> Optional["MemoryTools"]:
    """Parse the ``memory_tools`` setting into a :class:`MemoryTools`, or ``None``.

    Empty/unset means no explicit tools (pure automatic memory).
    """
    if not value:
        return None
    return MemoryTools(value)


def build_memory_toolset(
    tools: Optional["MemoryTools"],
    scope_level: ScopeLevel,
    agent_identity: Optional[str] = None,
) -> Optional[MemoryToolset]:
    """Return a ``MemoryToolset`` exposing the selected tools, or ``None`` when none."""
    expose_save = tools_expose_save(tools)
    expose_search = tools_expose_search(tools)
    if not (expose_save or expose_search):
        return None
    return MemoryToolset(
        scope_level,
        agent_identity,
        expose_save=expose_save,
        expose_search=expose_search,
    )
