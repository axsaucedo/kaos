"""Service settings: build the stores and the ``MemoryService`` from the environment.

The operator (a later phase) resolves a ``MemoryStore`` custom resource into these
environment variables; here we map them onto the typed config objects and construct
the live stores. Keeping construction in one place lets the entrypoint and the
container share exactly the same wiring.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from kaos_memory.background import BackgroundRunner
from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    ModelConfig,
    StorageConfig,
    WorkingTierConfig,
)
from kaos_memory.longterm import LongTermStore
from kaos_memory.models import ModelClient
from kaos_memory.service import MemoryService
from kaos_memory.working import WorkingStore


class MemorySettings(BaseSettings):
    """Environment-driven configuration for the memory service.

    All variables are prefixed ``KAOS_MEMORY_``. Exactly one storage block is used
    depending on ``storage_type``.
    """

    model_config = SettingsConfigDict(env_prefix="KAOS_MEMORY_", extra="ignore")

    storage_type: str = "local"

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
    rolling_summary: bool = True
    hard_event_cap: int = 2000

    extraction_concurrency: int = 4
    extraction_max_retries: int = 2

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

    def working_tier(self) -> WorkingTierConfig:
        return WorkingTierConfig(
            token_budget=self.token_budget,
            rolling_summary=self.rolling_summary,
            hard_event_cap=self.hard_event_cap,
        )

    def working_target(self) -> str:
        """SQLite file path (local) or Postgres DSN (external) for the working table."""
        if self.storage_type == "local":
            return f"{self.local_path.rstrip('/')}/working.db"
        return self.external_dsn


def build_service(settings: MemorySettings) -> MemoryService:
    """Construct the long-term and working stores and wrap them in a ``MemoryService``."""
    storage = settings.storage()
    longterm = LongTermStore(storage, settings.summarization(), settings.embedding())
    summarizer = ModelClient(settings.summarization()).as_summarizer()
    working = WorkingStore(
        settings.storage_type,
        settings.working_target(),
        settings.working_tier(),
        summarizer,
    )
    runner = BackgroundRunner(
        concurrency=settings.extraction_concurrency,
        max_retries=settings.extraction_max_retries,
    )
    return MemoryService(longterm=longterm, working=working, scheduler=runner)
