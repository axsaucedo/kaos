"""Typed configuration for the memory stores.

These objects are plain data: the storage backend selection, the model bindings
(a resolved OpenAI-compatible endpoint plus a model name, mirroring the Agent's
``{modelAPI, model}`` shape), and the short-term tier behaviour. Resolution from a
``MemoryStore`` custom resource happens in the operator; the stores here take the
already-resolved configuration.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

StorageType = Literal["local", "external"]
LocalProvider = Literal["chroma"]
ExternalProvider = Literal["pgvector"]


class LocalStorage(BaseModel):
    """Embedded single-container storage: Chroma + SQLite on one directory (PVC)."""

    provider: LocalProvider = "chroma"
    path: str = Field(
        description="Directory root holding the Chroma collection and SQLite short-term table."
    )
    collection_name: str = "kaos_memory"


class ExternalStorage(BaseModel):
    """Shared stateless storage: pgvector + a short-term table on one Postgres."""

    provider: ExternalProvider = "pgvector"
    dsn: str = Field(
        description="Postgres DSN/connection string for both the vector store and the short-term table."
    )
    collection_name: str = "kaos_memory"
    embedding_dims: int = Field(
        default=1536,
        description="Embedding dimension; required by pgvector (Chroma infers it).",
    )


class StorageConfig(BaseModel):
    """Selects and configures the storage mode. Exactly one block matches ``type``."""

    type: StorageType
    local: Optional[LocalStorage] = None
    external: Optional[ExternalStorage] = None

    def resolved(self) -> LocalStorage | ExternalStorage:
        """Return the active storage block, raising if it is missing for the selected type."""
        if self.type == "local":
            if self.local is None:
                raise ValueError("storage.type is 'local' but no local block was provided")
            return self.local
        if self.external is None:
            raise ValueError("storage.type is 'external' but no external block was provided")
        return self.external


class ModelConfig(BaseModel):
    """A resolved model binding: an OpenAI-compatible base URL, a model name, and a key.

    Used for both the summarization/extraction LLM and the embedding model, mirroring
    the Agent's ``{modelAPI, model}`` configuration. The base URL is the endpoint a KAOS
    ModelAPI (LiteLLM proxy) exposes.
    """

    base_url: str
    model: str
    api_key: str = "kaos"


class ShortTermTierConfig(BaseModel):
    """Short-term tier behaviour: a token budget bounding the verbatim window, an
    opt-in rolling summary that folds overflow (instead of dropping it), and a hard
    event cap ceiling. Summarization is disabled by default — a bounded recency
    window suffices for most agents; enable ``rolling_summary`` to fold overflow.

    Folding is governed by two water marks rather than a single budget so that eviction
    is amortised instead of thrashing near the limit. ``high_water`` is the token level
    at which folding is triggered; ``low_water`` is the token level folding evicts back
    down to. When left at ``0`` they default to the budget (trigger) and half the budget
    (target). Constraint: ``0 < low_water < high_water <= token_budget``."""

    token_budget: int = 4096
    rolling_summary: bool = False
    hard_event_cap: int = 2000
    high_water: int = 0
    low_water: int = 0
    digest_retention: int = 20

    @model_validator(mode="after")
    def _resolve_water_marks(self) -> "ShortTermTierConfig":
        if self.high_water == 0:
            self.high_water = self.token_budget
        if self.low_water == 0:
            self.low_water = max(1, self.token_budget // 2)
        if self.hard_event_cap < 1:
            raise ValueError("hard_event_cap must be >= 1")
        if self.digest_retention < 1:
            raise ValueError("digest_retention must be >= 1")
        if not 0 < self.low_water < self.high_water <= self.token_budget:
            raise ValueError(
                "short-term water marks must satisfy " "0 < low_water < high_water <= token_budget"
            )
        return self
