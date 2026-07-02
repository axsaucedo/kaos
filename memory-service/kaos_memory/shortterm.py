"""Short-term store: a relational short-term conversation buffer.

The short-term tier is a plain relational table (SQLite for ``local`` mode, Postgres
for ``external`` mode) holding recent turns. A token budget bounds the verbatim
window; when appending a turn pushes the active window past the budget (or a hard
event-count ceiling), the oldest active turns are folded into a *rolling summary*
rather than truncated, so nothing is silently lost and the summary stays
re-derivable from the retained raw rows.

The store is scope-keyed: each scope (typically a session) gets its own window
and summary. Eviction-by-summarization replaces the old turn-count eviction.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.scope import Scope
from kaos_memory.tokens import count_tokens

#: A summarizer folds (prior_summary, [(role, content), ...]) into a new summary.
Summarizer = Callable[[str, List[Tuple[str, str]]], str]


def scope_key(scope: Scope) -> str:
    """Stable string key for a scope's short-term window (one owner key -> 'key:value')."""
    ((key, value),) = scope.owner_kwargs().items()
    return f"{key}:{value}"


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
            f"CREATE TABLE IF NOT EXISTS working_turns ("
            f"id {serial}, scope_key TEXT, role TEXT, content TEXT, "
            f"created_at DOUBLE PRECISION, folded INTEGER DEFAULT 0)"
            if self.kind == "external"
            else (
                f"CREATE TABLE IF NOT EXISTS working_turns ("
                f"id {serial}, scope_key TEXT, role TEXT, content TEXT, "
                f"created_at REAL, folded INTEGER DEFAULT 0)"
            )
        )
        self.execute(
            "CREATE TABLE IF NOT EXISTS working_summary (scope_key TEXT PRIMARY KEY, text TEXT)"
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
    """Token-budgeted, scope-keyed short-term memory with a rolling summary."""

    def __init__(
        self,
        storage_type: str,
        target: str,
        config: Optional[ShortTermTierConfig] = None,
        summarizer: Optional[Summarizer] = None,
    ) -> None:
        """Args:
        storage_type: ``local`` (SQLite) or ``external`` (Postgres).
        target: SQLite file path or Postgres DSN.
        config: short-term tier behaviour (token budget, rolling summary, hard cap).
        summarizer: folds overflow into a rolling summary; required when
            ``config.rolling_summary`` is True.
        """
        self.cfg = config or ShortTermTierConfig()
        self.summarizer = summarizer
        self.db = _Backend(storage_type, target)
        # Serializes read-modify-write paths (append/clear) since the service runs
        # handlers on a threadpool over a single shared connection.
        self._lock = threading.RLock()

    def append(self, scope: Scope, role: str, content: str, metadata: Any = None) -> None:
        """Append a turn and re-enforce the budget and hard cap by summarizing overflow."""
        key = scope_key(scope)
        with self._lock:
            self.db.execute(
                "INSERT INTO working_turns (scope_key, role, content, created_at, folded) "
                "VALUES (?, ?, ?, ?, 0)",
                (key, role, content, time.time()),
            )
            self.db.commit()
            self._enforce(key)

    def _active(self, key: str) -> List[Tuple[int, str, str]]:
        cur = self.db.execute(
            "SELECT id, role, content FROM working_turns WHERE scope_key = ? AND folded = 0 "
            "ORDER BY id",
            (key,),
        )
        return list(cur.fetchall())

    def _active_tokens(self, active: List[Tuple[int, str, str]]) -> int:
        return sum(count_tokens(c) for _, _, c in active)

    def _summary(self, key: str) -> str:
        cur = self.db.execute("SELECT text FROM working_summary WHERE scope_key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else ""

    def _over_limit(self, active: List[Tuple[int, str, str]]) -> bool:
        if len(active) > self.cfg.hard_event_cap:
            return True
        return self._active_tokens(active) > self.cfg.token_budget

    def _enforce(self, key: str) -> None:
        # Fold oldest active turns into the rolling summary until back within limits,
        # never dropping the single most recent turn.
        while True:
            active = self._active(key)
            if len(active) <= 1 or not self._over_limit(active):
                break
            fold_id, fold_role, fold_content = active[0]
            if self.cfg.rolling_summary:
                if self.summarizer is None:
                    raise ValueError("rolling_summary is enabled but no summarizer was provided")
                new_summary = self.summarizer(self._summary(key), [(fold_role, fold_content)])
                self.db.execute(
                    "INSERT INTO working_summary (scope_key, text) VALUES (?, ?) "
                    "ON CONFLICT(scope_key) DO UPDATE SET text = excluded.text",
                    (key, new_summary),
                )
            self.db.execute("UPDATE working_turns SET folded = 1 WHERE id = ?", (fold_id,))
            self.db.commit()

    def recent(self, scope: Scope, token_budget: Optional[int] = None) -> List[Tuple[str, str]]:
        """Return the active verbatim window as ordered (role, content), within the budget."""
        key = scope_key(scope)
        budget = token_budget if token_budget is not None else self.cfg.token_budget
        active = self._active(key)
        # Trim from the oldest end to honour an explicit smaller budget for this read.
        total = self._active_tokens(active)
        while active and total > budget and len(active) > 1:
            _, _, content = active.pop(0)
            total -= count_tokens(content)
        return [(r, c) for _, r, c in active]

    def summary(self, scope: Scope) -> str:
        """Return the current rolling summary text for the scope (empty if none)."""
        return self._summary(scope_key(scope))

    def context(self, scope: Scope) -> Tuple[str, List[Tuple[str, str]]]:
        """Return (rolling_summary, active_window) — the full short-term context for a run."""
        return self.summary(scope), self.recent(scope)

    def clear(self, scope: Scope) -> None:
        """Delete all turns and the summary for the scope."""
        key = scope_key(scope)
        with self._lock:
            self.db.execute("DELETE FROM working_turns WHERE scope_key = ?", (key,))
            self.db.execute("DELETE FROM working_summary WHERE scope_key = ?", (key,))
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def ping(self) -> None:
        """Probe working-table reachability with a trivial query; raises if unreachable."""
        self.db.execute("SELECT 1").fetchone()
