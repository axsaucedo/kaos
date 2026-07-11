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
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

import httpx
import tiktoken

from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    ModelConfig,
    ShortTermTierConfig,
    StorageConfig,
)
from kaos_memory.contract import (
    SHARED_OWNER,
    Scope,
    ScopeLevel,
    scope_key,
)

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

    def __init__(
        self,
        config: ModelConfig,
        client: Optional[httpx.Client] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30.0)
        self._system_prompt = system_prompt or _SUMMARY_SYSTEM

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
                    {"role": "system", "content": self._system_prompt},
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


def _window_table_ddl(kind: str, serial: str) -> str:
    """DDL for the verbatim short-term window.

    On Postgres the window is an UNLOGGED table: it skips WAL/fsync for RAM-speed
    writes and stays coherent across replicas (it is still a shared table), at the cost
    of being truncated on crash recovery and unavailable on physical replicas — an
    acceptable trade for an ephemeral recency window. SQLite has no such distinction.
    """
    ts_type = "DOUBLE PRECISION" if kind == "external" else "REAL"
    unlogged = "UNLOGGED " if kind == "external" else ""
    return (
        f"CREATE {unlogged}TABLE IF NOT EXISTS short_term_memory_window ("
        f"id {serial}, scope_key TEXT, role TEXT, content TEXT, "
        f"created_at {ts_type}, pending_summary INTEGER DEFAULT 0)"
    )


def _summary_table_ddl(kind: str) -> str:
    """DDL for the versioned medium-term digest, which stays durable (logged)."""
    ts_type = "DOUBLE PRECISION" if kind == "external" else "REAL"
    return (
        "CREATE TABLE IF NOT EXISTS medium_term_memory_summaries ("
        f"scope_key TEXT, version INTEGER, text TEXT, tokens INTEGER, "
        f"created_at {ts_type}, PRIMARY KEY (scope_key, version))"
    )


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
        self.execute(_window_table_ddl(self.kind, serial))
        self.execute(_summary_table_ddl(self.kind))
        self.commit()

    @contextmanager
    def scope_lock(self, key: str) -> Iterator[None]:
        """Serialise a per-scope critical section across processes.

        On Postgres this takes a session-level advisory lock keyed on the scope so that
        concurrent agent replicas (separate connections) cannot fold the same scope twice
        or interleave a consolidation; it is released on exit. On SQLite it is a no-op —
        a single-process embedded store is already serialised by the in-process lock.
        """
        if self.kind != "external":
            yield
            return
        self.execute("SELECT pg_advisory_lock(hashtext(?)::bigint)", (key,))
        self.commit()
        try:
            yield
        finally:
            self.execute("SELECT pg_advisory_unlock(hashtext(?)::bigint)", (key,))
            self.commit()

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> Any:
        sql = sql.replace("?", self.ph) if self.ph != "?" else sql
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq_of_params: List[Tuple[Any, ...]]) -> Any:
        sql = sql.replace("?", self.ph) if self.ph != "?" else sql
        cur = self._conn.cursor()
        cur.executemany(sql, seq_of_params)
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
    - ``rolling_summary`` enabled: overflow is marked pending and folded, in one
      summariser call, into a new append-only version of the medium-term digest (prior
      versions are retained up to a cap, never mutated), then deleted. When a
      ``scheduler`` is injected the fold runs off the response hot path; otherwise inline.
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

    def add(self, scope: Scope, turns: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """Append a batch of turns, enforce the budget/cap, and return the evicted turns.

        ``turns`` is an ordered ``(role, content)`` list appended in a single transaction;
        the overflow is computed once after the whole batch has landed. The returned
        ``(role, content)`` list is the batch that just left the verbatim window. It is the
        cascade seam: callers forward it to long-term extraction so facts are captured from
        evicted history (whether the medium-term digest is enabled or not), while the digest
        fold consumes the same batch independently. Empty when the appends did not push the
        window over its limits.
        """
        if not turns:
            return []
        key = scope_key(scope)
        now = time.time()
        with self._lock:
            self.db.executemany(
                "INSERT INTO short_term_memory_window "
                "(scope_key, role, content, created_at, pending_summary) "
                "VALUES (?, ?, ?, ?, 0)",
                [(key, role, content, now) for role, content in turns],
            )
            self.db.commit()
            overflow = self._overflow_window_rows(key)
        self._drop_stale_window(scope, key, [rid for rid, _, _ in overflow])
        return [(r, c) for _, r, c in overflow]

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
        """Fold all pending (marked) turns for the scope into a new digest version.

        Reads every turn marked ``pending_summary=1``, folds them into the prior digest
        with a single summariser call, appends the result as a new version (append-only,
        never mutating prior versions), prunes versions beyond the retention cap, and
        deletes the folded rows so the window does not grow unboundedly. Safe to call more
        than once (extra calls with no pending rows are no-ops). Invoked inline or via the
        injected scheduler.
        """
        if self.summarizer is None:
            raise ValueError("rolling_summary is enabled but no summarizer was provided")
        key = scope_key(scope)
        with self._lock, self.db.scope_lock(key):
            pending = self._load_pending_summary_rows(key)
            if not pending:
                return
            turns = [(role, content) for _, role, content in pending]
            new_summary = self.summarizer(self._load_summary(key), turns)
            next_version = self._next_summary_version(key)
            self.db.execute(
                "INSERT INTO medium_term_memory_summaries "
                "(scope_key, version, text, tokens, created_at) VALUES (?, ?, ?, ?, ?)",
                (key, next_version, new_summary, count_tokens(new_summary), time.time()),
            )
            self._prune_summary_versions(key, next_version)
            for fid, _, _ in pending:
                self.db.execute("DELETE FROM short_term_memory_window WHERE id = ?", (fid,))
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def ping(self) -> None:
        """Probe short-term table reachability with a trivial query; raises if unreachable."""
        with self._lock:
            self.db.execute("SELECT 1").fetchone()

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

    def _overflow_window_rows(self, key: str) -> List[Tuple[int, str, str]]:
        """Oldest active rows to evict, amortised via compaction marks (keep >=1).

        Folding is triggered when the window exceeds ``compaction_trigger`` tokens or the
        hard event cap; once triggered, the oldest turns are evicted down to the
        ``compaction_target`` token target (and within the hard event cap). Evicting to the
        target rather than to just-under-budget amortises the fold frequency and avoids
        thrashing a fold on nearly every turn once the window sits at the limit. Returns
        full ``(id, role, content)`` rows so callers can both delete them and forward
        their content to long-term extraction.
        """
        active = self._load_active_window_rows(key)
        total = self._window_token_total(active)
        n = len(active)
        if not (total > self.cfg.compaction_trigger or n > self.cfg.hard_event_cap):
            return []
        rows: List[Tuple[int, str, str]] = []
        i = 0
        while n - i > 1 and (
            total > self.cfg.compaction_target or (n - i) > self.cfg.hard_event_cap
        ):
            rid, role, content = active[i]
            rows.append((rid, role, content))
            total -= count_tokens(content)
            i += 1
        return rows

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
            "SELECT text FROM medium_term_memory_summaries WHERE scope_key = ? "
            "ORDER BY version DESC LIMIT 1",
            (key,),
        )
        row = cur.fetchone()
        return row[0] if row else ""

    def _next_summary_version(self, key: str) -> int:
        cur = self.db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM medium_term_memory_summaries "
            "WHERE scope_key = ?",
            (key,),
        )
        row = cur.fetchone()
        return int(row[0]) + 1

    def _prune_summary_versions(self, key: str, latest_version: int) -> None:
        """Delete digest versions older than the retention window (keep the last N)."""
        oldest_kept = latest_version - self.cfg.digest_retention
        if oldest_kept < 1:
            return
        self.db.execute(
            "DELETE FROM medium_term_memory_summaries WHERE scope_key = ? AND version <= ?",
            (key, oldest_kept),
        )


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
        system_prompt: Optional[str] = None,
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
        # Mem0 uses this system prompt to steer which facts it extracts from a
        # turn; unset leaves its built-in default extraction prompt in place.
        if system_prompt:
            config["custom_fact_extraction_prompt"] = system_prompt
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
