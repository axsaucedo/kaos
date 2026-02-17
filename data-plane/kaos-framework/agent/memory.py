"""
Agent memory and session management.

Simple, clean implementation similar to Google ADK's InMemorySessionService.
Provides session management, event logging, and context building for agents.

Three implementations:
- LocalMemory: Full in-memory storage with session/event limits
- RedisMemory: Distributed storage backed by Redis
- NullMemory: No-op implementation when memory is disabled
"""

import json
import uuid
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, Any, List, Optional, Union, Deque
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MemoryEvent:
    """Represents a single event in agent session memory."""

    event_id: str
    timestamp: datetime
    event_type: str  # "user_message", "agent_response", "tool_call", "reasoning"
    content: Any
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data["event_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            event_type=data["event_type"],
            content=data["content"],
            metadata=data["metadata"],
        )


@dataclass
class SessionMemory:
    """Represents a complete session with all its events.

    Uses deque for automatic bounded storage - oldest events are automatically
    evicted when max_events is reached.
    """

    session_id: str
    user_id: str
    app_name: str
    events: Deque[MemoryEvent] = field(default_factory=deque)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "app_name": self.app_name,
            "events": [event.to_dict() for event in self.events],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class LocalMemory:
    """Local in-memory session storage similar to Google ADK's InMemorySessionService."""

    def __init__(self, max_sessions: int = 1000, max_events_per_session: int = 500):
        """Initialize local memory storage.

        Args:
            max_sessions: Maximum number of sessions to keep in memory
            max_events_per_session: Maximum events per session before cleanup
        """
        self._sessions: Dict[str, SessionMemory] = {}
        self.max_sessions = max_sessions
        self.max_events_per_session = max_events_per_session

        logger.info(
            f"LocalMemory initialized: max_sessions={max_sessions}, max_events_per_session={max_events_per_session}"
        )

    async def create_session(
        self, app_name: str, user_id: str, session_id: Optional[str] = None
    ) -> str:
        """Create a new session.

        Args:
            app_name: Name of the application
            user_id: User identifier
            session_id: Optional custom session ID

        Returns:
            The session ID
        """
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc)
        # Use deque with maxlen for automatic bounded event storage
        session = SessionMemory(
            session_id=session_id,
            user_id=user_id,
            app_name=app_name,
            events=deque(maxlen=self.max_events_per_session),
            created_at=now,
            updated_at=now,
        )

        # Cleanup old sessions if needed
        await self._cleanup_sessions_if_needed()

        self._sessions[session_id] = session
        logger.debug(f"Created session: {session_id} for user: {user_id}")
        return session_id

    async def get_session(self, session_id: str) -> Optional[SessionMemory]:
        """Retrieve a session by ID.

        Args:
            session_id: The session ID

        Returns:
            SessionMemory or None if not found
        """
        return self._sessions.get(session_id)

    async def get_or_create_session(
        self, session_id: str, app_name: str = "agent", user_id: str = "user"
    ) -> str:
        """Get existing session or create a new one with the given ID.

        Args:
            session_id: The session ID to get or create
            app_name: Name of the application (used if creating)
            user_id: User identifier (used if creating)

        Returns:
            The session ID (same as input)
        """
        if session_id not in self._sessions:
            await self.create_session(app_name, user_id, session_id)
            logger.debug(f"Created new session for provided ID: {session_id}")
        return session_id

    async def add_event(
        self,
        session_id: str,
        event_or_type: Union[MemoryEvent, str],
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Add an event to a session.

        Supports two call patterns:
        1. add_event(session_id, event)  - Pass a MemoryEvent object
        2. add_event(session_id, event_type, content, metadata)  - Create and add in one call

        Uses deque with maxlen for automatic O(1) bounded storage.
        Oldest events are automatically evicted when limit is reached.

        Args:
            session_id: The session ID
            event_or_type: Either a MemoryEvent or event type string
            content: Event content (required if event_or_type is a string)
            metadata: Optional metadata dictionary

        Returns:
            True if added successfully, False if session not found
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found, event not added")
            return False

        # Handle both call patterns
        if isinstance(event_or_type, MemoryEvent):
            event = event_or_type
        else:
            event = self.create_event(event_or_type, content, metadata)

        # Deque handles automatic eviction - no cleanup needed
        session.events.append(event)
        session.updated_at = datetime.now(timezone.utc)
        logger.debug(f"Added {event.event_type} event to session {session_id}")
        return True

    async def get_session_events(
        self, session_id: str, event_types: Optional[List[str]] = None
    ) -> List[MemoryEvent]:
        """Get events for a session, optionally filtered by type.

        Args:
            session_id: The session ID
            event_types: Optional list of event types to filter by

        Returns:
            List of events, filtered by type if specified
        """
        session = await self.get_session(session_id)
        if not session:
            return []

        # Convert deque to list for consistent return type
        events = list(session.events)
        if event_types:
            events = [e for e in events if e.event_type in event_types]

        return events

    async def build_conversation_context(self, session_id: str, max_events: int = 20) -> str:
        events = await self.get_session_events(session_id, ["user_message", "agent_response"])

        # Get most recent events
        recent_events = events[-max_events:] if len(events) > max_events else events

        if not recent_events:
            return ""

        context_lines = []
        for event in recent_events:
            if event.event_type == "user_message":
                context_lines.append(f"User: {event.content}")
            elif event.event_type == "agent_response":
                context_lines.append(f"Assistant: {event.content}")

        return "\n".join(context_lines)

    def create_event(
        self, event_type: str, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryEvent:
        """Create a memory event.

        Args:
            event_type: Type of event (e.g., "user_message", "agent_response")
            content: Event content/data
            metadata: Optional metadata dictionary

        Returns:
            MemoryEvent instance

        If OpenTelemetry is enabled, automatically includes trace_id and span_id
        in the metadata for log correlation.
        """
        from telemetry.manager import is_otel_enabled, get_current_trace_context

        event_metadata = metadata.copy() if metadata else {}

        # Add trace context if OTel is enabled
        if is_otel_enabled():
            trace_ctx = get_current_trace_context()
            if trace_ctx:
                event_metadata.update(trace_ctx)

        return MemoryEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            content=content,
            metadata=event_metadata,
        )

    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]:
        """Get list of session IDs, optionally filtered by user.

        Args:
            user_id: Optional user ID to filter sessions

        Returns:
            List of session IDs
        """
        if user_id:
            return [sid for sid, session in self._sessions.items() if session.user_id == user_id]
        return list(self._sessions.keys())

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The session ID

        Returns:
            True if deleted, False if not found
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug(f"Deleted session: {session_id}")
            return True
        return False

    async def get_memory_stats(self) -> Dict[str, int]:
        """Get memory usage statistics.

        Returns:
            Dictionary with memory statistics
        """
        total_events = sum(len(session.events) for session in self._sessions.values())
        return {
            "total_sessions": len(self._sessions),
            "total_events": total_events,
            "avg_events_per_session": (
                int(total_events / len(self._sessions)) if self._sessions else 0
            ),
        }

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up sessions older than specified age.

        Args:
            max_age_hours: Maximum session age in hours

        Returns:
            Number of sessions cleaned up
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        sessions_to_delete = []

        for session_id, session in self._sessions.items():
            if session.updated_at < cutoff_time:
                sessions_to_delete.append(session_id)

        for session_id in sessions_to_delete:
            del self._sessions[session_id]

        if sessions_to_delete:
            logger.info(f"Cleaned up {len(sessions_to_delete)} old sessions")

        return len(sessions_to_delete)

    async def _cleanup_sessions_if_needed(self):
        """Remove oldest sessions if we exceed the limit."""
        if len(self._sessions) >= self.max_sessions:
            # Remove oldest 10% of sessions
            sessions_to_remove = max(1, self.max_sessions // 10)

            # Sort by updated_at to find oldest
            sorted_sessions = sorted(self._sessions.items(), key=lambda x: x[1].updated_at)

            for session_id, _ in sorted_sessions[:sessions_to_remove]:
                del self._sessions[session_id]

            logger.info(f"Cleaned up {sessions_to_remove} oldest sessions to stay under limit")


class NullMemory:
    """No-op memory implementation for when memory is disabled.

    All methods succeed silently without storing any data.
    This avoids adding conditional checks throughout the agent code.
    """

    def __init__(self, *args, **kwargs):
        """Accept any arguments for compatibility with LocalMemory signature."""
        logger.info("NullMemory initialized (memory disabled)")

    async def create_session(
        self, app_name: str = "", user_id: str = "", session_id: Optional[str] = None
    ) -> str:
        """Return a constant session ID."""
        return session_id or "null-session"

    async def get_session(self, session_id: str) -> Optional[SessionMemory]:
        """Always returns None."""
        return None

    async def get_or_create_session(
        self, session_id: str, app_name: str = "agent", user_id: str = "user"
    ) -> str:
        """Return the provided session ID."""
        return session_id

    async def add_event(
        self,
        session_id: str,
        event_or_type: Union[Optional[MemoryEvent], str] = None,
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Silently accept and discard events."""
        return True

    async def get_session_events(
        self, session_id: str, event_types: Optional[List[str]] = None
    ) -> List[MemoryEvent]:
        """Always returns empty list."""
        return []

    async def build_conversation_context(self, session_id: str, max_events: int = 20) -> str:
        """Always returns empty string."""
        return ""

    def create_event(
        self, event_type: str, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryEvent:
        """Create a memory event (even though it won't be stored)."""
        return MemoryEvent(
            event_id=f"null_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            content=content,
            metadata=metadata or {},
        )

    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]:
        """Always returns empty list."""
        return []

    async def delete_session(self, session_id: str) -> bool:
        """Always returns True."""
        return True

    async def get_memory_stats(self) -> Dict[str, int]:
        """Return zero stats."""
        return {
            "total_sessions": 0,
            "total_events": 0,
            "avg_events_per_session": 0,
        }

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """No-op cleanup."""
        return 0


class RedisMemory:
    """Distributed memory backed by Redis.

    Uses Redis hashes for session metadata and sorted sets for events.
    Provides the same interface as LocalMemory but with distributed storage.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_sessions: int = 1000,
        max_events_per_session: int = 500,
        key_prefix: str = "kaos:memory",
    ):
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise ImportError("redis package required for RedisMemory: pip install redis")

        self._redis: aioredis.Redis = aioredis.from_url(redis_url, decode_responses=True)
        self.max_sessions = max_sessions
        self.max_events_per_session = max_events_per_session
        self._prefix = key_prefix

        logger.info(
            f"RedisMemory initialized: url={redis_url}, max_sessions={max_sessions}, "
            f"max_events_per_session={max_events_per_session}"
        )

    def _session_key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{session_id}"

    def _events_key(self, session_id: str) -> str:
        return f"{self._prefix}:events:{session_id}"

    def _sessions_index_key(self) -> str:
        return f"{self._prefix}:sessions"

    async def create_session(
        self, app_name: str, user_id: str, session_id: Optional[str] = None
    ) -> str:
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc)
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "app_name": app_name,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        await self._cleanup_sessions_if_needed()

        pipe = self._redis.pipeline()
        pipe.hset(self._session_key(session_id), mapping=session_data)
        pipe.zadd(self._sessions_index_key(), {session_id: now.timestamp()})
        await pipe.execute()

        logger.debug(f"Created session: {session_id} for user: {user_id}")
        return session_id

    async def get_session(self, session_id: str) -> Optional[SessionMemory]:
        data = await self._redis.hgetall(self._session_key(session_id))  # ty: ignore[invalid-await]
        if not data:
            return None

        events = await self._get_raw_events(session_id)
        return SessionMemory(
            session_id=data["session_id"],
            user_id=data["user_id"],
            app_name=data["app_name"],
            events=deque(events, maxlen=self.max_events_per_session),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    async def get_or_create_session(
        self, session_id: str, app_name: str = "agent", user_id: str = "user"
    ) -> str:
        exists = await self._redis.exists(self._session_key(session_id))
        if not exists:
            await self.create_session(app_name, user_id, session_id)
            logger.debug(f"Created new session for provided ID: {session_id}")
        return session_id

    async def add_event(
        self,
        session_id: str,
        event_or_type: Union[MemoryEvent, str],
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        exists = await self._redis.exists(self._session_key(session_id))
        if not exists:
            logger.warning(f"Session {session_id} not found, event not added")
            return False

        if isinstance(event_or_type, MemoryEvent):
            event = event_or_type
        else:
            event = self.create_event(event_or_type, content, metadata)

        now = datetime.now(timezone.utc)
        event_json = json.dumps(event.to_dict())

        pipe = self._redis.pipeline()
        pipe.zadd(self._events_key(session_id), {event_json: now.timestamp()})
        pipe.hset(self._session_key(session_id), "updated_at", now.isoformat())
        pipe.zadd(self._sessions_index_key(), {session_id: now.timestamp()})
        await pipe.execute()

        # Trim to max events
        count = await self._redis.zcard(self._events_key(session_id))
        if count > self.max_events_per_session:
            await self._redis.zremrangebyrank(
                self._events_key(session_id), 0, count - self.max_events_per_session - 1
            )

        logger.debug(f"Added {event.event_type} event to session {session_id}")
        return True

    async def get_session_events(
        self, session_id: str, event_types: Optional[List[str]] = None
    ) -> List[MemoryEvent]:
        events = await self._get_raw_events(session_id)
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        return events

    async def _get_raw_events(self, session_id: str) -> List[MemoryEvent]:
        raw = await self._redis.zrange(self._events_key(session_id), 0, -1)
        events = []
        for item in raw:
            try:
                events.append(MemoryEvent.from_dict(json.loads(item)))
            except (json.JSONDecodeError, KeyError):
                logger.warning(f"Skipping malformed event in session {session_id}")
        return events

    async def build_conversation_context(self, session_id: str, max_events: int = 20) -> str:
        events = await self.get_session_events(session_id, ["user_message", "agent_response"])
        recent_events = events[-max_events:] if len(events) > max_events else events

        if not recent_events:
            return ""

        context_lines = []
        for event in recent_events:
            if event.event_type == "user_message":
                context_lines.append(f"User: {event.content}")
            elif event.event_type == "agent_response":
                context_lines.append(f"Assistant: {event.content}")

        return "\n".join(context_lines)

    def create_event(
        self, event_type: str, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryEvent:
        from telemetry.manager import is_otel_enabled, get_current_trace_context

        event_metadata = metadata.copy() if metadata else {}

        if is_otel_enabled():
            trace_ctx = get_current_trace_context()
            if trace_ctx:
                event_metadata.update(trace_ctx)

        return MemoryEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            content=content,
            metadata=event_metadata,
        )

    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]:
        session_ids = await self._redis.zrange(self._sessions_index_key(), 0, -1)
        if not user_id:
            return session_ids

        filtered = []
        for sid in session_ids:
            stored_uid = await self._redis.hget(
                self._session_key(sid), "user_id"
            )  # ty: ignore[invalid-await]
            if stored_uid == user_id:
                filtered.append(sid)
        return filtered

    async def delete_session(self, session_id: str) -> bool:
        exists = await self._redis.exists(self._session_key(session_id))
        if not exists:
            return False

        pipe = self._redis.pipeline()
        pipe.delete(self._session_key(session_id))
        pipe.delete(self._events_key(session_id))
        pipe.zrem(self._sessions_index_key(), session_id)
        await pipe.execute()

        logger.debug(f"Deleted session: {session_id}")
        return True

    async def get_memory_stats(self) -> Dict[str, int]:
        total_sessions = await self._redis.zcard(self._sessions_index_key())
        total_events = 0
        session_ids = await self._redis.zrange(self._sessions_index_key(), 0, -1)
        for sid in session_ids:
            total_events += await self._redis.zcard(self._events_key(sid))

        return {
            "total_sessions": total_sessions,
            "total_events": total_events,
            "avg_events_per_session": (int(total_events / total_sessions) if total_sessions else 0),
        }

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        old_sessions = await self._redis.zrangebyscore(
            self._sessions_index_key(), "-inf", cutoff.timestamp()
        )

        for sid in old_sessions:
            await self.delete_session(sid)

        if old_sessions:
            logger.info(f"Cleaned up {len(old_sessions)} old sessions")
        return len(old_sessions)

    async def _cleanup_sessions_if_needed(self):
        count = await self._redis.zcard(self._sessions_index_key())
        if count >= self.max_sessions:
            sessions_to_remove = max(1, self.max_sessions // 10)
            oldest = await self._redis.zrange(self._sessions_index_key(), 0, sessions_to_remove - 1)
            for sid in oldest:
                await self.delete_session(sid)
            logger.info(f"Cleaned up {len(oldest)} oldest sessions to stay under limit")


# Backwards compatibility - this is the main class to use
InMemorySessionService = LocalMemory
