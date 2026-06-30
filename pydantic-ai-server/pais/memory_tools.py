"""Opt-in agent memory tools and recall-presentation gating.

The runtime presents recalled long-term memory to the agent in one of two ways,
selected per agent by ``recall.presentation``:

- ``block`` (default): the recalled context is assembled by the service and
  injected into the run as a structured context block; the agent does not call
  any tool.
- ``tools``: the agent is given explicit ``save_memory`` / ``search_memory``
  tools and decides when to read or write long-term memory.
- ``both``: the block is injected *and* the tools are available.

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


class RecallPresentation(str, Enum):
    """How recalled long-term memory is surfaced to the agent."""

    BLOCK = "block"
    TOOLS = "tools"
    BOTH = "both"


def presentation_injects_block(presentation: "RecallPresentation") -> bool:
    """True when the recalled block should be injected into the run context."""
    return presentation in (RecallPresentation.BLOCK, RecallPresentation.BOTH)


def presentation_exposes_tools(presentation: "RecallPresentation") -> bool:
    """True when the save/search memory tools should be registered."""
    return presentation in (RecallPresentation.TOOLS, RecallPresentation.BOTH)


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
            ok = await memory.write(scope, "user", content, infer=True)
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


def build_memory_toolset(
    presentation: "RecallPresentation",
    scope_level: ScopeLevel,
    agent_identity: Optional[str] = None,
) -> Optional[MemoryToolset]:
    """Return a ``MemoryToolset`` when the presentation exposes tools, else ``None``."""
    if not presentation_exposes_tools(presentation):
        return None
    return MemoryToolset(scope_level, agent_identity)
