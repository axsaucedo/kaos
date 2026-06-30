"""Typed configuration for the memory stores.

These objects are plain data: the storage backend selection, the model bindings
(a resolved OpenAI-compatible endpoint plus a model name, mirroring the Agent's
``{modelAPI, model}`` shape), and the working-tier behaviour. Resolution from a
``MemoryStore`` custom resource happens in the operator; the stores here take the
already-resolved configuration.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

StorageType = Literal["local", "external"]
LocalProvider = Literal["chroma"]
ExternalProvider = Literal["pgvector"]


class LocalStorage(BaseModel):
    """Embedded single-container storage: Chroma + SQLite on one directory (PVC)."""

    provider: LocalProvider = "chroma"
    path: str = Field(
        description="Directory root holding the Chroma collection and SQLite working table."
    )
    collection_name: str = "kaos_memory"


class ExternalStorage(BaseModel):
    """Shared stateless storage: pgvector + a working table on one Postgres."""

    provider: ExternalProvider = "pgvector"
    dsn: str = Field(
        description="Postgres DSN/connection string for both the vector store and the working table."
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


class WorkingTierConfig(BaseModel):
    """Working-tier behaviour: a token budget bounding the verbatim window, a rolling
    summary that folds overflow (instead of truncating), and a hard event cap ceiling."""

    token_budget: int = 4096
    rolling_summary: bool = True
    hard_event_cap: int = 2000
