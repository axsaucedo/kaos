"""Agent memory and session management with Local and Null backends."""

import json
import uuid
import logging
import httpx
from abc import ABC, abstractmethod
from collections import deque
from inspect import isawaitable
from typing import Dict, Any, List, Optional, Tuple, Union, Deque, Mapping
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from kaos_memory.contract import Attribution, Scope, ScopeLevel
from kaos_memory.client import (
    MemoryServiceClient,
    RecalledMemory,
    LongTermRecall,
    ShortTermRecall,
    MediumTermRecall,
)
from kaos_memory.pydantic_ai import (
    attribution_from_deps,
    scope_from_deps,
    pydantic_message_to_turns,
    reconstruct_message_history,
)

# Back-compat alias: the runtime historically named the scope MemoryScope; it is
# the shared contract Scope, re-exported so existing imports keep working.
MemoryScope = Scope
MemoryAttribution = Attribution

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
    """Abstract interface for all memory implementations.

    The interface is tiered. The session/event methods below model the short-term
    tier the message-history bridge replays. The ``recall``/``write``/``forget``
    methods model the long-term tier served by the central memory service. A
    short-term-only or disabled backend inherits the long-term methods as no-ops, so
    only a service-backed implementation needs to override them.
    """

    async def recall(
        self,
        scope: "MemoryScope",
        query: str,
        *,
        top_k: int = 10,
        include: Optional[List[str]] = None,
        token_budget: Optional[int] = None,
    ) -> "RecalledMemory":
        """Assemble the context visible at ``scope`` for ``query``.

        Best-effort: a long-term failure yields a degraded, short-term-only (or empty)
        result rather than raising. The default implementation recalls nothing,
        which is correct for short-term-only and disabled backends.
        """
        return RecalledMemory()

    async def write(
        self,
        attribution: "MemoryAttribution",
        turns: List[Tuple[str, str]],
        *,
        infer: bool = True,
        failure_mode: Optional[str] = None,
    ) -> bool:
        """Record a batch of turns into the memory tiers off the hot path.

        ``turns`` is an ordered ``(role, content)`` list persisted in a single call so a
        whole interaction lands as one write. ``failure_mode`` is optional: when ``None``
        the memory store's own configured default governs fail-soft vs strict; pass an
        explicit ``"soft"``/``"strict"`` only to override it. Returns ``True`` when the
        write was accepted. The default implementation is a no-op accept for backends
        without a long-term tier.
        """
        return True

    async def forget(self, scope: "MemoryScope", *, failure_mode: Optional[str] = None) -> bool:
        """Erase a scope: clear its short-term tier and delete its long-term memories.

        ``failure_mode`` is optional; when ``None`` the store's configured default
        governs fail-soft vs strict. The default implementation is a no-op accept for
        backends without a long-term tier.
        """
        return True

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
        from pais.telemetry import is_otel_enabled, get_current_trace_context

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

        prompt_types = ("user_message",)
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


class RemoteMemory(Memory):
    """Memory backend that calls the central memory service over HTTP.

    Implements the long-term tier — ``recall``/``write``/``forget`` — against the
    service's HTTP surface, and treats every call as best-effort: transport
    failures and degraded responses never raise into the agent turn (unless the
    caller selects ``failure_mode="strict"`` for a write/forget). The short-term tier
    lives in the service and is returned *inside* the recall response, so the
    legacy session/event methods are thin no-ops here; the message-history bridge
    reads the short-term slice from ``recall`` rather than from local event storage.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 10.0,
        recall_timeout: float = 5.0,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._service = MemoryServiceClient(
            endpoint, timeout=timeout, recall_timeout=recall_timeout, client=client
        )
        self.endpoint = self._service.endpoint

    async def recall(
        self,
        scope: "MemoryScope",
        query: str,
        *,
        top_k: int = 10,
        include: Optional[List[str]] = None,
        token_budget: Optional[int] = None,
    ) -> "RecalledMemory":
        return await self._service.recall(
            scope,
            query,
            top_k=top_k,
            include=include,
            token_budget=token_budget,
        )

    async def write(
        self,
        attribution: "MemoryAttribution",
        turns: List[Tuple[str, str]],
        *,
        infer: bool = True,
        failure_mode: Optional[str] = None,
    ) -> bool:
        return await self._service.write(attribution, turns, infer=infer, failure_mode=failure_mode)

    async def forget(self, scope: "MemoryScope", *, failure_mode: Optional[str] = None) -> bool:
        return await self._service.forget(scope, failure_mode=failure_mode)

    async def close(self) -> None:
        await self._service.close()

    # The short-term tier lives in the service and is returned inside recall, so
    # these satisfy the interface without holding local session state.

    async def create_session(
        self, app_name: str = "agent", user_id: str = "user", session_id: Optional[str] = None
    ) -> str:
        return session_id or f"session_{uuid.uuid4().hex[:12]}"

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
