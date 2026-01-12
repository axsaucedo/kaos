"""
Agent memory and session management.

Simple, clean implementation similar to Google ADK's InMemorySessionService.
Provides session management, event logging, and context building for agents.
"""

import uuid
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

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
    """Represents a complete session with all its events."""

    session_id: str
    user_id: str
    app_name: str
    events: List[MemoryEvent]
    created_at: datetime
    updated_at: datetime

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
        session = SessionMemory(
            session_id=session_id,
            user_id=user_id,
            app_name=app_name,
            events=[],
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

    async def add_event(self, session_id: str, event: MemoryEvent) -> bool:
        """Add an event to a session.

        Args:
            session_id: The session ID
            event: The event to add

        Returns:
            True if added successfully, False if session not found
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found, event not added")
            return False

        # Cleanup old events if needed
        await self._cleanup_events_if_needed(session)

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

        events = session.events
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
        """
        return MemoryEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            content=content,
            metadata=metadata or {},
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

    async def _cleanup_events_if_needed(self, session: SessionMemory):
        """Remove oldest events from session if we exceed the limit."""
        if len(session.events) >= self.max_events_per_session:
            # Keep most recent 80% of events
            events_to_keep = int(self.max_events_per_session * 0.8)
            removed_count = len(session.events) - events_to_keep

            session.events = session.events[-events_to_keep:]

            logger.debug(
                f"Cleaned up {removed_count} oldest events from session {session.session_id}"
            )


# Backwards compatibility - this is the main class to use
InMemorySessionService = LocalMemory
