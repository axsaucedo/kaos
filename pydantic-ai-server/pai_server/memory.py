"""Agent memory and session management with Local, Redis, and Null backends."""

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
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEvent":
        return cls(
            event_id=data["event_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            event_type=data["event_type"],
            content=data["content"],
            metadata=data["metadata"],
        )


@dataclass
class SessionMemory:
    """Complete session with bounded event storage (deque with maxlen)."""

    session_id: str
    user_id: str
    app_name: str
    events: Deque[MemoryEvent] = field(default_factory=deque)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "app_name": self.app_name,
            "events": [event.to_dict() for event in self.events],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Memory(ABC):
    """Abstract interface for all memory implementations."""

    @abstractmethod
    async def create_session(
        self, app_name: str, user_id: str, session_id: Optional[str] = None
    ) -> str: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[SessionMemory]: ...

    @abstractmethod
    async def get_or_create_session(
        self, session_id: str, app_name: str = "agent", user_id: str = "user"
    ) -> str: ...

    @abstractmethod
    async def add_event(
        self,
        session_id: str,
        event_or_type: Union[MemoryEvent, str],
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool: ...

    @abstractmethod
    async def get_session_events(
        self, session_id: str, event_types: Optional[List[str]] = None
    ) -> List[MemoryEvent]: ...

    @abstractmethod
    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]: ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool: ...

    def create_event(
        self, event_type: str, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryEvent:
        """Create a MemoryEvent with optional OTEL trace context."""
        from pai_server.telemetry import is_otel_enabled, get_current_trace_context

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

    async def build_conversation_context(self, session_id: str, max_events: int = 20) -> str:
        """Build a text conversation context from memory events."""
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

    async def build_message_history(
        self, session_id: str, context_limit: int = 6
    ) -> Optional[list]:
        """Build Pydantic AI message_history from stored KAOS events.

        Excludes the latest prompt event (current user message) and respects context_limit.
        """
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse as PydanticModelResponse,
            TextPart,
            UserPromptPart,
        )

        events = await self.get_session_events(session_id)
        if not events or len(events) <= 1:
            return None

        prompt_types = ("user_message", "task_delegation_received")
        exclude_idx = next(
            (i for i in range(len(events) - 1, -1, -1) if events[i].event_type in prompt_types),
            None,
        )
        replayable = [e for i, e in enumerate(events) if i != exclude_idx]

        if context_limit and len(replayable) > context_limit:
            replayable = replayable[-context_limit:]

        history: list = []
        for event in replayable:
            if event.event_type in prompt_types:
                history.append(ModelRequest(parts=[UserPromptPart(content=str(event.content))]))
            elif event.event_type == "agent_response":
                history.append(PydanticModelResponse(parts=[TextPart(content=str(event.content))]))
        return history or None

    async def store_pydantic_message(self, session_id: str, msg: Any) -> None:
        """Convert Pydantic AI messages (tool calls/returns) into KAOS memory events."""
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse as PydanticModelResponse,
            TextPart,
            ToolCallPart,
            ToolReturnPart,
        )

        if isinstance(msg, PydanticModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    is_deleg = part.tool_name.startswith("delegate_to_")
                    await self.add_event(
                        session_id,
                        "delegation_request" if is_deleg else "tool_call",
                        {"tool": part.tool_name, "arguments": part.args},
                    )
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    is_deleg = part.tool_name.startswith("delegate_to_")
                    result = part.content
                    if isinstance(result, (dict, list)):
                        result_value = result
                    elif isinstance(result, str):
                        try:
                            result_value = json.loads(result)
                        except (json.JSONDecodeError, ValueError):
                            result_value = result
                    else:
                        result_value = str(result)
                    await self.add_event(
                        session_id,
                        "delegation_response" if is_deleg else "tool_result",
                        {"tool": part.tool_name, "result": result_value},
                    )

    async def get_memory_stats(self) -> Dict[str, int]:
        """Get memory usage statistics. Override for real implementations."""
        return {"total_sessions": 0, "total_events": 0, "avg_events_per_session": 0}

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up old sessions. Override for real implementations."""
        return 0

    async def close(self) -> None:
        """Close the memory backend. Override for backends with connections."""
        pass


class LocalMemory(Memory):
    """Local in-memory session storage similar to Google ADK's InMemorySessionService."""

    def __init__(self, max_sessions: int = 1000, max_events_per_session: int = 500):
        self._sessions: Dict[str, SessionMemory] = {}
        self.max_sessions = max_sessions
        self.max_events_per_session = max_events_per_session

        logger.info(
            f"LocalMemory initialized: max_sessions={max_sessions}, max_events_per_session={max_events_per_session}"
        )

    async def create_session(
        self, app_name: str, user_id: str, session_id: Optional[str] = None
    ) -> str:
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
        return self._sessions.get(session_id)

    async def get_or_create_session(
        self, session_id: str, app_name: str = "agent", user_id: str = "user"
    ) -> str:
        # TODO: Add asyncio.Lock to prevent race condition in concurrent requests
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
        """Accepts either a MemoryEvent or (event_type, content, metadata) args.

        Uses deque with maxlen for automatic O(1) bounded storage.
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
        session = await self.get_session(session_id)
        if not session:
            return []

        # Convert deque to list for consistent return type
        events = list(session.events)
        if event_types:
            events = [e for e in events if e.event_type in event_types]

        return events

    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]:
        if user_id:
            return [sid for sid, session in self._sessions.items() if session.user_id == user_id]
        return list(self._sessions.keys())

    async def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug(f"Deleted session: {session_id}")
            return True
        return False

    async def get_memory_stats(self) -> Dict[str, int]:
        total_events = sum(len(session.events) for session in self._sessions.values())
        return {
            "total_sessions": len(self._sessions),
            "total_events": total_events,
            "avg_events_per_session": (
                int(total_events / len(self._sessions)) if self._sessions else 0
            ),
        }

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
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


class NullMemory(Memory):
    """No-op memory — all methods succeed silently without storing data."""

    def __init__(self, *args, **kwargs):
        logger.info("NullMemory initialized (memory disabled)")

    async def create_session(
        self, app_name: str = "", user_id: str = "", session_id: Optional[str] = None
    ) -> str:
        return session_id or "null-session"

    async def get_session(self, session_id: str) -> Optional[SessionMemory]:
        return None

    async def get_or_create_session(
        self, session_id: str, app_name: str = "agent", user_id: str = "user"
    ) -> str:
        return session_id

    async def add_event(
        self,
        session_id: str,
        event_or_type: Union[MemoryEvent, str] = "",
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return True

    async def get_session_events(
        self, session_id: str, event_types: Optional[List[str]] = None
    ) -> List[MemoryEvent]:
        return []

    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]:
        return []

    async def delete_session(self, session_id: str) -> bool:
        return True


class RedisMemory(Memory):
    """Distributed memory backed by Redis.

    Storage model:
    - Session metadata: Redis hash (HSET/HGETALL)
    - Events: Redis list (RPUSH/LRANGE) — append-only conversation log
    - Session index: Redis sorted set (ZADD/ZRANGE) — for listing/cleanup
    - TTL: EXPIRE on session and event keys for automatic retention
    - Writes: Single pipeline (RPUSH + LTRIM + HSET + ZADD) for atomicity
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_sessions: int = 1000,
        max_events_per_session: int = 500,
        key_prefix: str = "kaos:memory",
        session_ttl_hours: int = 24,
    ):
        import redis.asyncio as aioredis

        self._redis: aioredis.Redis = aioredis.from_url(redis_url, decode_responses=True)
        self.max_sessions = max_sessions
        self.max_events_per_session = max_events_per_session
        self._prefix = key_prefix
        self._session_ttl = session_ttl_hours * 3600

        logger.info(
            f"RedisMemory initialized: url={redis_url}, max_sessions={max_sessions}, "
            f"max_events={max_events_per_session}, ttl={session_ttl_hours}h"
        )

    def _session_key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{session_id}"

    def _events_key(self, session_id: str) -> str:
        return f"{self._prefix}:events:{session_id}"

    def _sessions_index_key(self) -> str:
        return f"{self._prefix}:sessions"

    async def close(self):
        try:
            await self._redis.aclose()
            logger.debug("RedisMemory connection closed")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")

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
        pipe.expire(self._session_key(session_id), self._session_ttl)
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
        # TODO: Use Redis SETNX for atomic check-and-create to prevent race condition
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

        # Atomic pipeline: append event, trim to cap, update session, refresh index/TTL
        pipe = self._redis.pipeline()
        pipe.rpush(self._events_key(session_id), event_json)
        pipe.ltrim(self._events_key(session_id), -self.max_events_per_session, -1)
        pipe.hset(self._session_key(session_id), "updated_at", now.isoformat())
        pipe.zadd(self._sessions_index_key(), {session_id: now.timestamp()})
        pipe.expire(self._session_key(session_id), self._session_ttl)
        pipe.expire(self._events_key(session_id), self._session_ttl)
        await pipe.execute()

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
        raw = await self._redis.lrange(
            self._events_key(session_id), 0, -1
        )  # ty: ignore[invalid-await]
        events = []
        seen_ids: set = set()
        for item in raw:
            try:
                data = json.loads(item)
                eid = data.get("event_id", "")
                if eid and eid in seen_ids:
                    continue
                if eid:
                    seen_ids.add(eid)
                events.append(MemoryEvent.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning(f"Skipping malformed event in session {session_id}")
        return events

    async def list_sessions(self, user_id: Optional[str] = None) -> List[str]:
        session_ids = await self._redis.zrange(self._sessions_index_key(), 0, -1)

        # Session index hygiene: remove stale entries whose keys have expired
        stale = []
        live = []
        for sid in session_ids:
            exists = await self._redis.exists(self._session_key(sid))
            if exists:
                live.append(sid)
            else:
                stale.append(sid)
        if stale:
            pipe = self._redis.pipeline()
            for sid in stale:
                pipe.zrem(self._sessions_index_key(), sid)
            await pipe.execute()
            logger.debug(f"Reaped {len(stale)} stale session index entries")

        if not user_id:
            return live

        filtered = []
        for sid in live:
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
        session_ids = await self._redis.zrange(self._sessions_index_key(), 0, -1)

        total_events = 0
        if session_ids:
            pipe = self._redis.pipeline()
            for sid in session_ids:
                pipe.llen(self._events_key(sid))
            lengths = await pipe.execute()
            total_events = sum(lengths)

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
