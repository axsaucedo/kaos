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
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    Folding is governed by two compaction marks rather than a single budget so that
    eviction is amortised instead of thrashing near the limit. ``compaction_trigger`` is
    the token level at which folding is triggered; ``compaction_target`` is the token level
    folding evicts back down to. When left at ``0`` they default to the budget (trigger) and
    half the budget (target). Constraint: ``0 < compaction_target < compaction_trigger <=
    token_budget``."""

    token_budget: int = 4096
    rolling_summary: bool = False
    hard_event_cap: int = 2000
    compaction_trigger: int = 0
    compaction_target: int = 0
    digest_retention: int = 20

    @model_validator(mode="after")
    def _resolve_compaction_marks(self) -> "ShortTermTierConfig":
        if self.compaction_trigger == 0:
            self.compaction_trigger = self.token_budget
        if self.compaction_target == 0:
            self.compaction_target = max(1, self.token_budget // 2)
        if self.hard_event_cap < 1:
            raise ValueError("hard_event_cap must be >= 1")
        if self.digest_retention < 1:
            raise ValueError("digest_retention must be >= 1")
        if not 0 < self.compaction_target < self.compaction_trigger <= self.token_budget:
            raise ValueError(
                "short-term compaction marks must satisfy "
                "0 < compaction_target < compaction_trigger <= token_budget"
            )
        return self


class MemorySettings(BaseSettings):
    """Environment-driven configuration for the memory service.

    The operator resolves a ``MemoryStore`` custom resource into these environment
    variables (all prefixed ``KAOS_MEMORY_``); here we map them onto the typed config
    objects above. Exactly one storage block is used depending on ``storage_type``.
    Rolling summarisation is off by default, matching ``ShortTermTierConfig``.
    """

    model_config = SettingsConfigDict(env_prefix="KAOS_MEMORY_", extra="ignore")

    storage_type: str = "local"

    require_principal: bool = False
    require_agent_identity: bool = False

    local_path: str = "/data/memory"
    local_collection: str = "kaos_memory"

    external_dsn: str = ""
    external_collection: str = "kaos_memory"
    external_dims: int = 1536

    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = "kaos"
    summarization_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    token_budget: int = 4096
    rolling_summary: bool = False
    hard_event_cap: int = 2000
    compaction_trigger: int = 0
    compaction_target: int = 0
    digest_retention: int = 20

    default_failure_mode: str = "soft"

    long_term_enabled: bool = True
    default_top_k: int = 10
    score_threshold: Optional[float] = None
    rerank: bool = False

    extraction_system_prompt: str = ""
    summarization_system_prompt: str = ""

    extraction_concurrency: int = 4
    extraction_max_retries: int = 2

    request_concurrency: int = 8

    host: str = "0.0.0.0"
    port: int = 8080

    def storage(self) -> StorageConfig:
        if self.storage_type == "local":
            return StorageConfig(
                type="local",
                local=LocalStorage(path=self.local_path, collection_name=self.local_collection),
            )
        if self.storage_type == "external":
            return StorageConfig(
                type="external",
                external=ExternalStorage(
                    dsn=self.external_dsn,
                    collection_name=self.external_collection,
                    embedding_dims=self.external_dims,
                ),
            )
        raise ValueError(f"unknown storage type: {self.storage_type}")

    def summarization(self) -> ModelConfig:
        return ModelConfig(
            base_url=self.model_base_url, model=self.summarization_model, api_key=self.model_api_key
        )

    def embedding(self) -> ModelConfig:
        return ModelConfig(
            base_url=self.model_base_url, model=self.embedding_model, api_key=self.model_api_key
        )

    def short_term_tier(self) -> ShortTermTierConfig:
        return ShortTermTierConfig(
            token_budget=self.token_budget,
            rolling_summary=self.rolling_summary,
            hard_event_cap=self.hard_event_cap,
            compaction_trigger=self.compaction_trigger,
            compaction_target=self.compaction_target,
            digest_retention=self.digest_retention,
        )

    def short_term_target(self) -> str:
        """SQLite file path (local) or Postgres DSN (external) for the short-term table."""
        if self.storage_type == "local":
            return f"{self.local_path.rstrip('/')}/shortterm.db"
        return self.external_dsn
