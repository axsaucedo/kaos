"""KAOS memory service.

The ``kaos_memory`` package houses the storage layer for KAOS production-grade
memory: a long-term adapter wrapping Mem0 as a library and a relational
short-term store with token-budget eviction and an opt-in rolling summary. Both
bind their models to a resolved OpenAI-compatible endpoint (a KAOS ModelAPI) and
run in either a ``local`` (embedded Chroma + SQLite) or ``external`` (pgvector +
Postgres) storage mode.
"""

from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    ModelConfig,
    ShortTermTierConfig,
    StorageConfig,
)
from kaos_memory.stores import (
    SHARED_OWNER,
    LongTermStore,
    ModelClient,
    Scope,
    ScopeLevel,
    ShortTermStore,
    count_tokens,
    scope_key,
)

__version__ = "0.4.8.dev0"

__all__ = [
    "ExternalStorage",
    "LocalStorage",
    "ModelConfig",
    "StorageConfig",
    "ShortTermTierConfig",
    "Scope",
    "ScopeLevel",
    "SHARED_OWNER",
    "ShortTermStore",
    "LongTermStore",
    "ModelClient",
    "count_tokens",
    "scope_key",
]
