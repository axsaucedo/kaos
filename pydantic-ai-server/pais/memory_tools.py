"""Backwards-compatible re-export of the memory toolset from ``kaos_memory``.

The opt-in memory tools and automatic-memory layering now live in the shared
``kaos-memory`` library under ``kaos_memory.pydantic_ai``. This module re-exports
them so existing ``pais.memory_tools`` imports keep working.

When memory is enabled the runtime always applies the automatic baseline: it
recalls relevant memory and injects it as a context block before the run, and
flushes the run's turns for extraction afterwards. On top of that baseline,
``memory.tools`` optionally exposes explicit agent-driven tools:

- ``read``: expose ``search_memory`` (the agent retrieves on demand).
- ``write``: expose ``save_memory`` (the agent saves on demand).
- ``all``: expose both.
- unset: no explicit tools (pure automatic).
"""

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
    "SAVE_MEMORY_TOOL",
    "SEARCH_MEMORY_TOOL",
    "MemoryTools",
    "MemoryToolset",
    "build_memory_toolset",
    "parse_memory_tools",
    "tools_expose_save",
    "tools_expose_search",
]
