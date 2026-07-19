"""Pydantic AI integration for KAOS memory (the ``pydantic-ai`` extra).

Re-exports the message/turn adapters and the memory toolset so consumers import
one place: ``from kaos_memory.pydantic_ai import scope_from_deps, MemoryToolset``.
Importing this package requires the ``pydantic-ai`` extra (the toolset depends on
Pydantic AI at import time).
"""

from kaos_memory.pydantic_ai.adapters import (
    attribution_from_deps,
    pydantic_message_to_turns,
    reconstruct_message_history,
    scope_from_deps,
)
from kaos_memory.pydantic_ai.toolset import (
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    MemoryTools,
    MemoryToolset,
    build_memory_toolset,
    parse_memory_tools,
    tools_expose_save,
    tools_expose_search,
)

__all__ = [
    "scope_from_deps",
    "attribution_from_deps",
    "pydantic_message_to_turns",
    "reconstruct_message_history",
    "MemoryTools",
    "MemoryToolset",
    "build_memory_toolset",
    "parse_memory_tools",
    "tools_expose_save",
    "tools_expose_search",
    "SAVE_MEMORY_TOOL",
    "SEARCH_MEMORY_TOOL",
]
