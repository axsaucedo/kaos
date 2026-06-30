"""Long-term memory adapter wrapping Mem0 as a library.

This module is the *only* importer of ``mem0``. It builds a Mem0 client from the
resolved storage and model configuration for either the ``local`` (embedded
Chroma) or ``external`` (pgvector) provider, and exposes scope-mapped
``write`` / ``recall`` / ``delete`` / ``delete_scope`` operations. Callers pass a
``Scope``; no Mem0 owner identifier leaks across the boundary.

Mem0's anonymous telemetry is disabled at import so the service never phones home
from a cluster.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

# Disable Mem0's anonymous PostHog telemetry before importing it. setdefault keeps
# an explicit operator override intact.
os.environ.setdefault("MEM0_TELEMETRY", "False")

from mem0 import Memory  # noqa: E402  (import after telemetry is disabled)

from kaos_memory.config import ExternalStorage, LocalStorage, ModelConfig, StorageConfig
from kaos_memory.scope import Scope


def _embedder_config(embedding: ModelConfig, dims: Optional[int]) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "model": embedding.model,
        "openai_base_url": embedding.base_url,
        "api_key": embedding.api_key,
    }
    # Chroma infers the dimension from the first vector and rejects the field;
    # pgvector requires it. Only set it when a dimension is provided.
    if dims is not None:
        config["embedding_dims"] = dims
    return config


def _llm_config(summarization: ModelConfig) -> Dict[str, Any]:
    return {
        "model": summarization.model,
        "openai_base_url": summarization.base_url,
        "api_key": summarization.api_key,
    }


def _vector_store_config(block: Union[LocalStorage, ExternalStorage]) -> Dict[str, Any]:
    if isinstance(block, LocalStorage):
        return {
            "provider": "chroma",
            "config": {"collection_name": block.collection_name, "path": block.path},
        }
    return {
        "provider": "pgvector",
        "config": {
            "connection_string": block.dsn,
            "collection_name": block.collection_name,
            "embedding_model_dims": block.embedding_dims,
        },
    }


class LongTermStore:
    """Scope-aware long-term memory backed by Mem0.

    Args:
        storage: selects and configures the vector store (local Chroma / external pgvector).
        summarization: the extraction LLM binding (an OpenAI-compatible ModelAPI endpoint).
        embedding: the embedding model binding.
    """

    def __init__(
        self,
        storage: StorageConfig,
        summarization: ModelConfig,
        embedding: ModelConfig,
    ) -> None:
        block = storage.resolved()
        # pgvector needs the embedding dimension; Chroma infers it.
        dims = block.embedding_dims if isinstance(block, ExternalStorage) else None
        config = {
            "llm": {"provider": "openai", "config": _llm_config(summarization)},
            "embedder": {"provider": "openai", "config": _embedder_config(embedding, dims)},
            "vector_store": _vector_store_config(block),
        }
        self._memory = Memory.from_config(config)

    @staticmethod
    def _results(raw: Any) -> List[Dict[str, Any]]:
        items = raw["results"] if isinstance(raw, dict) else raw
        return items or []

    def write(self, scope: Scope, messages: Any, infer: bool = True) -> List[Dict[str, Any]]:
        """Store ``messages`` under ``scope``. With ``infer`` the engine extracts facts."""
        raw = self._memory.add(messages, infer=infer, **scope.owner_kwargs())
        return self._results(raw)

    def recall(self, scope: Scope, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Return memories relevant to ``query`` visible at ``scope`` (pre-filtered by owner)."""
        raw = self._memory.search(query, filters=scope.search_filters(), top_k=top_k)
        return self._results(raw)

    def delete(self, memory_id: str) -> None:
        """Delete a single memory by id."""
        self._memory.delete(memory_id)

    def delete_scope(self, scope: Scope) -> None:
        """Erase every memory owned by ``scope`` (the scope-targeted erasure primitive)."""
        self._memory.delete_all(**scope.owner_kwargs())

    def ping(self) -> None:
        """Probe vector-store reachability without embedding (no model call).

        Lists collections on the underlying vector store; raises if the store is
        unreachable. Used by the service readiness check, which must reflect store
        reachability rather than model reachability (models bind lazily on first use).
        """
        self._memory.vector_store.list_cols()
