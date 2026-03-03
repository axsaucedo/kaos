"""A2A TaskStore: task lifecycle management with Local and Null backends."""

import uuid
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"


# Valid state transitions
VALID_TRANSITIONS: Dict[TaskState, set] = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED},
    TaskState.WORKING: {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.INPUT_REQUIRED,
    },
    TaskState.INPUT_REQUIRED: {TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELED: set(),
}

# Terminal states — no further transitions allowed
TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}


@dataclass
class TaskStatus:
    """Current status of a task including state, message, and timestamp."""

    state: TaskState
    message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "state": self.state.value,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.message is not None:
            d["message"] = self.message
        return d


@dataclass
class TaskMessage:
    """A2A message with role and text content."""

    role: str  # "user" or "agent"
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "parts": [{"type": "text", "text": self.text}]}


@dataclass
class Task:
    """A2A Task representing a unit of work with lifecycle tracking."""

    id: str
    session_id: str
    status: TaskStatus
    history: List[TaskMessage] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "status": self.status.to_dict(),
            "history": [m.to_dict() for m in self.history],
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }


class TaskStore(ABC):
    """Abstract interface for task lifecycle management."""

    @abstractmethod
    async def create_task(
        self,
        session_id: Optional[str] = None,
        input_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task: ...

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]: ...

    @abstractmethod
    async def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        message: Optional[str] = None,
    ) -> Optional[Task]: ...

    @abstractmethod
    async def set_task_output(self, task_id: str, output_text: str) -> Optional[Task]: ...

    @abstractmethod
    async def cancel_task(self, task_id: str) -> Optional[Task]: ...

    @abstractmethod
    async def list_tasks(self, session_id: Optional[str] = None) -> List[Task]: ...

    async def close(self) -> None:
        """Close the task store backend."""
        pass


class LocalTaskStore(TaskStore):
    """In-memory task store for single-pod deployments."""

    def __init__(self, max_tasks: int = 10000):
        self._tasks: Dict[str, Task] = {}
        self.max_tasks = max_tasks
        logger.info(f"LocalTaskStore initialized: max_tasks={max_tasks}")

    async def create_task(
        self,
        session_id: Optional[str] = None,
        input_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc)
        status = TaskStatus(state=TaskState.SUBMITTED, timestamp=now)

        history: List[TaskMessage] = []
        if input_message:
            history.append(TaskMessage(role="user", text=input_message))

        task = Task(
            id=task_id,
            session_id=session_id,
            status=status,
            history=history,
            metadata=metadata or {},
        )

        await self._cleanup_if_needed()
        self._tasks[task_id] = task
        logger.debug(f"Created task {task_id} in session {session_id}")
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    async def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        message: Optional[str] = None,
    ) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if not task:
            return None

        current = task.status.state
        if state not in VALID_TRANSITIONS.get(current, set()):
            logger.warning(
                f"Invalid transition {current.value} -> {state.value} for task {task_id}"
            )
            return None

        task.status = TaskStatus(
            state=state,
            message=message,
            timestamp=datetime.now(timezone.utc),
        )
        logger.debug(f"Task {task_id}: {current.value} -> {state.value}")
        return task

    async def set_task_output(self, task_id: str, output_text: str) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.history.append(TaskMessage(role="agent", text=output_text))
        return task

    async def cancel_task(self, task_id: str) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if not task:
            return None

        if task.status.state in TERMINAL_STATES:
            logger.debug(f"Task {task_id} already in terminal state {task.status.state.value}")
            return None

        return await self.update_task_state(task_id, TaskState.CANCELED, "Canceled by request")

    async def list_tasks(self, session_id: Optional[str] = None) -> List[Task]:
        if session_id:
            return [t for t in self._tasks.values() if t.session_id == session_id]
        return list(self._tasks.values())

    async def _cleanup_if_needed(self):
        if len(self._tasks) >= self.max_tasks:
            # Remove oldest completed/failed/canceled tasks first
            terminal = [
                (tid, t) for tid, t in self._tasks.items() if t.status.state in TERMINAL_STATES
            ]
            terminal.sort(key=lambda x: x[1].status.timestamp)
            to_remove = max(1, self.max_tasks // 10)
            for tid, _ in terminal[:to_remove]:
                del self._tasks[tid]
            logger.info(f"Cleaned up {min(to_remove, len(terminal))} old tasks")


class NullTaskStore(TaskStore):
    """No-op task store — all operations succeed silently."""

    def __init__(self, *args, **kwargs):
        logger.info("NullTaskStore initialized (task store disabled)")

    async def create_task(
        self,
        session_id: Optional[str] = None,
        input_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        task_id = f"null_task_{uuid.uuid4().hex[:8]}"
        return Task(
            id=task_id,
            session_id=session_id or "null-session",
            status=TaskStatus(state=TaskState.SUBMITTED),
        )

    async def get_task(self, task_id: str) -> Optional[Task]:
        return None

    async def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        message: Optional[str] = None,
    ) -> Optional[Task]:
        return None

    async def set_task_output(self, task_id: str, output_text: str) -> Optional[Task]:
        return None

    async def cancel_task(self, task_id: str) -> Optional[Task]:
        return None

    async def list_tasks(self, session_id: Optional[str] = None) -> List[Task]:
        return []
