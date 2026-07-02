"""Storage engine for KAOS memory: scope, tokens, model client, and the two stores.

This module is the whole storage layer, grouped by layer rather than split into
many single-responsibility files (KEEP IT SIMPLE):

- ``Scope`` / ``ScopeLevel`` / ``SHARED_OWNER`` — the identity every operation is
  keyed on, plus its translation to Mem0 owner identifiers.
- ``count_tokens`` / ``scope_key`` / ``Summarizer`` — small helpers the short-term
  store needs.
- ``ModelClient`` — an outbound OpenAI-compatible client the short-term store calls
  to produce its rolling summary.
- ``ShortTermStore`` — a token-budgeted relational conversation buffer with an
  opt-in rolling summary.
- ``LongTermStore`` — the Mem0 adapter (the only importer of ``mem0``).

Both stores expose a single ``add`` write verb and take an already-resolved
``StorageConfig`` / ``ModelConfig`` (config resolution lives in ``config.py``).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx
import tiktoken
from pydantic import BaseModel, model_validator

from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    ModelConfig,
    ShortTermTierConfig,
    StorageConfig,
)

# --------------------------------------------------------------------------- #
# Scope                                                                        #
# --------------------------------------------------------------------------- #

#: Reserved owner id naming the store-wide shared namespace. It is mapped onto
#: ``agent_id`` and is deliberately distinct from any real agent client id, so a
#: ``shared`` operation never collides with a ``private`` (per-agent) one.
SHARED_OWNER = "kaos:shared"


class ScopeLevel(str, Enum):
    """The memory scope an operation targets.

    - ``PRIVATE``: only this agent (mapped to ``agent_id``).
    - ``USER``: all agents acting for a principal (mapped to ``user_id``).
    - ``SHARED``: every agent on the store (mapped to the reserved shared owner).
    - ``SESSION``: a single run/conversation (mapped to ``run_id``).
    """

    PRIVATE = "private"
    USER = "user"
    SHARED = "shared"
    SESSION = "session"


class Scope(BaseModel):
    """Identifies the owner of a memory operation.

    Carries the principal, the agent's stable client id, and the session id, plus
    the selected ``level``. Only the field required by ``level`` must be present;
    the rest may be unset (an under-specified scope is representable here and is
    rejected by enforcement later, not by construction).
    """

    level: ScopeLevel
    principal: Optional[str] = None
    agent_client_id: Optional[str] = None
    session_id: Optional[str] = None

    @model_validator(mode="after")
    def _normalise(self) -> "Scope":
        # Empty strings are treated as unset so they cannot be used as owner keys.
        for field in ("principal", "agent_client_id", "session_id"):
            value = getattr(self, field)
            if value is not None and value.strip() == "":
                object.__setattr__(self, field, None)
        return self

    def is_complete(self) -> bool:
        """Whether the field required by ``level`` is present (a usable owner key exists)."""
        if self.level is ScopeLevel.PRIVATE:
            return self.agent_client_id is not None
        if self.level is ScopeLevel.USER:
            return self.principal is not None
        if self.level is ScopeLevel.SESSION:
            return self.session_id is not None
        return True  # SHARED always resolves to the reserved owner.

    def owner_kwargs(self) -> Dict[str, Any]:
        """Return the Mem0 owner keyword arguments for a write/search at this scope.

        Exactly one of ``user_id`` / ``agent_id`` / ``run_id`` is set. Raises if the
        field required by ``level`` is missing, so an unusable scope never silently
        widens to another owner.
        """
        if self.level is ScopeLevel.PRIVATE:
            if self.agent_client_id is None:
                raise ValueError("private scope requires agent_client_id")
            return {"agent_id": self.agent_client_id}
        if self.level is ScopeLevel.USER:
            if self.principal is None:
                raise ValueError("user scope requires principal")
            return {"user_id": self.principal}
        if self.level is ScopeLevel.SESSION:
            if self.session_id is None:
                raise ValueError("session scope requires session_id")
            return {"run_id": self.session_id}
        return {"agent_id": SHARED_OWNER}

    def search_filters(self) -> Dict[str, Any]:
        """Return the Mem0 ``filters`` dict for a search at this scope.

        Identical to the owner kwargs: Mem0 2.x uses the same owner keys inside the
        ``filters`` argument and requires at least one of them, which this always
        provides.
        """
        return self.owner_kwargs()


# --------------------------------------------------------------------------- #
# Token counting and short-term helpers                                        #
# --------------------------------------------------------------------------- #

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the token count of ``text`` under the cl100k_base encoding.

    A stable, model-agnostic approximation: the short-term tier only needs a
    consistent measure to bound its verbatim window, not exact per-model accounting.
    """
    if not text:
        return 0
    return len(_ENCODING.encode(text))


def scope_key(scope: Scope) -> str:
    """Stable string key for a scope's short-term window (one owner key -> 'key:value')."""
    ((key, value),) = scope.owner_kwargs().items()
    return f"{key}:{value}"


#: A summarizer folds (prior_summary, [(role, content), ...]) into a new summary.
Summarizer = Callable[[str, List[Tuple[str, str]]], str]

#: Runs a thunk (typically off the response hot path). Injected by the service.
Scheduler = Callable[[Callable[[], None]], None]


# --------------------------------------------------------------------------- #
# Model client                                                                 #
# --------------------------------------------------------------------------- #

_SUMMARY_SYSTEM = (
    "You maintain a concise rolling summary of a conversation. Fold the prior summary "
    "and the provided older turns into an updated summary that preserves durable facts, "
    "decisions, and entities. Return only the summary text."
)


class ModelClient:
    """Calls an OpenAI-compatible chat endpoint for short-term tier summarization.

    This is an outbound dependency the short-term store uses; Mem0 owns its own
    embedding/extraction calls, configured from the same ``ModelConfig`` values.
    """

    def __init__(self, config: ModelConfig, client: Optional[httpx.Client] = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30.0)

    def summarize(self, prior_summary: str, folded_turns: List[Tuple[str, str]]) -> str:
        """Fold ``prior_summary`` and ``folded_turns`` into an updated rolling summary."""
        turns_text = "\n".join(f"{role}: {content}" for role, content in folded_turns)
        user = (
            f"Prior summary:\n{prior_summary or '(none)'}\n\nOlder turns to fold in:\n{turns_text}"
        )
        resp = self._client.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def as_summarizer(self) -> Summarizer:
        """Return a ``Summarizer`` callable for use by the short-term store."""
        return self.summarize

    def close(self) -> None:
        self._client.close()


# --------------------------------------------------------------------------- #
# Short-term store                                                             #
# --------------------------------------------------------------------------- #


class _Backend:
    """Thin DB abstraction over SQLite and Postgres with a single schema.

    Hides the parameter-placeholder and serial-type differences so the store logic
    is written once. ``local`` -> sqlite3; ``external`` -> psycopg.
    """

    def __init__(self, storage_type: str, target: str):
        self.kind = storage_type
        self._conn: Any
        if storage_type == "local":
            self._conn = sqlite3.connect(target, check_same_thread=False)
            self.ph = "?"
            serial = "INTEGER PRIMARY KEY AUTOINCREMENT"
        elif storage_type == "external":
            import psycopg

            self._conn = psycopg.connect(target)
            self.ph = "%s"
            serial = "BIGSERIAL PRIMARY KEY"
        else:
            raise ValueError(f"unknown storage type: {storage_type}")
        self._ensure_schema(serial)

    def _ensure_schema(self, serial: str) -> None:
        self.execute(
            f"CREATE TABLE IF NOT EXISTS short_term_memory_window ("
            f"id {serial}, scope_key TEXT, role TEXT, content TEXT, "
            f"created_at DOUBLE PRECISION, pending_summary INTEGER DEFAULT 0)"
            if self.kind == "external"
            else (
                f"CREATE TABLE IF NOT EXISTS short_term_memory_window ("
                f"id {serial}, scope_key TEXT, role TEXT, content TEXT, "
                f"created_at REAL, pending_summary INTEGER DEFAULT 0)"
            )
        )
        self.execute(
            "CREATE TABLE IF NOT EXISTS medium_term_memory_summaries "
            "(scope_key TEXT PRIMARY KEY, text TEXT)"
        )
        self.commit()

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> Any:
        sql = sql.replace("?", self.ph) if self.ph != "?" else sql
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class ShortTermStore:
    """Token-budgeted, scope-keyed short-term memory with an opt-in rolling summary.

    Recent turns are kept verbatim until the token budget (or a hard event-count cap)
    is reached. On overflow the oldest turns beyond the budget are evicted, always
    keeping at least the most recent turn:

    - ``rolling_summary`` disabled (default): overflow is dropped (a recency window).
    - ``rolling_summary`` enabled: overflow is marked pending and folded into a single
      rolling summary in one summariser call, then deleted. When a ``scheduler`` is
      injected the fold runs off the response hot path; otherwise it runs inline.
    """

    def __init__(
        self,
        storage_type: str,
        target: str,
        config: Optional[ShortTermTierConfig] = None,
        summarizer: Optional[Summarizer] = None,
        scheduler: Optional[Scheduler] = None,
    ) -> None:
        """Args:
        storage_type: ``local`` (SQLite) or ``external`` (Postgres).
        target: SQLite file path or Postgres DSN.
        config: short-term tier behaviour (token budget, rolling summary, hard cap).
        summarizer: folds overflow into a rolling summary; required when
            ``config.rolling_summary`` is True.
        scheduler: runs the fold off the response path; if absent, folds inline.
        """
        self.cfg = config or ShortTermTierConfig()
        self.summarizer = summarizer
        self._scheduler = scheduler
        self._lock = threading.Lock()
        self.db = _Backend(storage_type, target)

    def add(self, scope: Scope, role: str, content: str) -> None:
        """Append a turn, then re-enforce the budget and hard cap."""
        key = scope_key(scope)
        with self._lock:
            self.db.execute(
                "INSERT INTO short_term_memory_window "
                "(scope_key, role, content, created_at, pending_summary) "
                "VALUES (?, ?, ?, ?, 0)",
                (key, role, content, time.time()),
            )
            self.db.commit()
            overflow_ids = self._ids_exceeding_budget(key)
        self._drop_stale_window(scope, key, overflow_ids)

    def active_window(
        self, scope: Scope, token_budget: Optional[int] = None
    ) -> List[Tuple[str, str]]:
        """Return the active verbatim window as ordered (role, content), within the budget."""
        key = scope_key(scope)
        budget = token_budget if token_budget is not None else self.cfg.token_budget
        with self._lock:
            active = self._load_active_window_rows(key)
        # Trim from the oldest end to honour an explicit smaller budget for this read.
        total = self._window_token_total(active)
        while active and total > budget and len(active) > 1:
            _, _, content = active.pop(0)
            total -= count_tokens(content)
        return [(r, c) for _, r, c in active]

    def summary(self, scope: Scope) -> str:
        """Return the current medium-term summary text for the scope (empty if none)."""
        with self._lock:
            return self._load_summary(scope_key(scope))

    def short_term_context(self, scope: Scope) -> Tuple[str, List[Tuple[str, str]]]:
        """Return (medium_term_summary, active_window) — the full short-term context for a run."""
        return self.summary(scope), self.active_window(scope)

    def clear(self, scope: Scope) -> None:
        """Delete all turns and the summary for the scope."""
        key = scope_key(scope)
        with self._lock:
            self.db.execute("DELETE FROM short_term_memory_window WHERE scope_key = ?", (key,))
            self.db.execute("DELETE FROM medium_term_memory_summaries WHERE scope_key = ?", (key,))
            self.db.commit()

    def fold_pending_into_summary(self, scope: Scope) -> None:
        """Fold all pending (marked) turns for the scope into the summary in one call.

        Reads every turn marked ``pending_summary=1``, folds them into the prior summary
        with a single summariser call, upserts the summary, and deletes the folded rows so
        the store does not grow unboundedly. Safe to call more than once (extra calls with
        no pending rows are no-ops). Invoked inline or via the injected scheduler.
        """
        if self.summarizer is None:
            raise ValueError("rolling_summary is enabled but no summarizer was provided")
        key = scope_key(scope)
        with self._lock:
            pending = self._load_pending_summary_rows(key)
            if not pending:
                return
            turns = [(role, content) for _, role, content in pending]
            new_summary = self.summarizer(self._load_summary(key), turns)
            self.db.execute(
                "INSERT INTO medium_term_memory_summaries (scope_key, text) VALUES (?, ?) "
                "ON CONFLICT(scope_key) DO UPDATE SET text = excluded.text",
                (key, new_summary),
            )
            for fid, _, _ in pending:
                self.db.execute("DELETE FROM short_term_memory_window WHERE id = ?", (fid,))
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- internals -------------------------------------------------------- #

    def _drop_stale_window(self, scope: Scope, key: str, overflow_ids: List[int]) -> None:
        """Evict the computed overflow: drop it (recency window) or fold it (rolling summary)."""
        if not overflow_ids:
            return
        if not self.cfg.rolling_summary:
            with self._lock:
                for oid in overflow_ids:
                    self.db.execute("DELETE FROM short_term_memory_window WHERE id = ?", (oid,))
                self.db.commit()
            return
        with self._lock:
            for oid in overflow_ids:
                self.db.execute(
                    "UPDATE short_term_memory_window SET pending_summary = 1 WHERE id = ?",
                    (oid,),
                )
            self.db.commit()
        if self._scheduler is not None:
            self._scheduler(lambda: self.fold_pending_into_summary(scope))
        else:
            self.fold_pending_into_summary(scope)

    def _ids_exceeding_budget(self, key: str) -> List[int]:
        """Ids of the oldest active turns to evict to get back within limits (keep >=1)."""
        active = self._load_active_window_rows(key)
        ids: List[int] = []
        total = self._window_token_total(active)
        i = 0
        while len(active) - i > 1 and (
            len(active) - i > self.cfg.hard_event_cap or total > self.cfg.token_budget
        ):
            rid, _, content = active[i]
            ids.append(rid)
            total -= count_tokens(content)
            i += 1
        return ids

    def _load_active_window_rows(self, key: str) -> List[Tuple[int, str, str]]:
        cur = self.db.execute(
            "SELECT id, role, content FROM short_term_memory_window "
            "WHERE scope_key = ? AND pending_summary = 0 ORDER BY id",
            (key,),
        )
        return list(cur.fetchall())

    def _load_pending_summary_rows(self, key: str) -> List[Tuple[int, str, str]]:
        cur = self.db.execute(
            "SELECT id, role, content FROM short_term_memory_window "
            "WHERE scope_key = ? AND pending_summary = 1 ORDER BY id",
            (key,),
        )
        return list(cur.fetchall())

    def _window_token_total(self, active: List[Tuple[int, str, str]]) -> int:
        return sum(count_tokens(c) for _, _, c in active)

    def _load_summary(self, key: str) -> str:
        cur = self.db.execute(
            "SELECT text FROM medium_term_memory_summaries WHERE scope_key = ?", (key,)
        )
        row = cur.fetchone()
        return row[0] if row else ""


# --------------------------------------------------------------------------- #
# Long-term store (Mem0 adapter)                                               #
# --------------------------------------------------------------------------- #

# Disable Mem0's anonymous PostHog telemetry before importing it. setdefault keeps
# an explicit operator override intact.
os.environ.setdefault("MEM0_TELEMETRY", "False")

from mem0 import Memory  # noqa: E402  (import after telemetry is disabled)


def _history_db_path(block: Union[LocalStorage, ExternalStorage]) -> str:
    """Resolve where Mem0 keeps its change-history SQLite log.

    The history log is an audit trail, not load-bearing for recall. In ``local`` mode
    it lives alongside the vector store on the PVC so it persists with the container.
    In ``external`` (stateless, horizontally-scaled) mode it is kept on an ephemeral
    per-replica path so the shared Postgres vector store - not a per-replica SQLite
    file - is the only thing that must be shared, which is what allows scaling out.
    """
    if isinstance(block, LocalStorage):
        return f"{block.path.rstrip('/')}/mem0_history.db"
    return os.path.join(tempfile.gettempdir(), "kaos_mem0_history.db")


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
            "history_db_path": _history_db_path(block),
        }
        self._memory = Memory.from_config(config)

    @staticmethod
    def _results(raw: Any) -> List[Dict[str, Any]]:
        items = raw["results"] if isinstance(raw, dict) else raw
        return items or []

    def add(self, scope: Scope, messages: Any, infer: bool = True) -> List[Dict[str, Any]]:
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
