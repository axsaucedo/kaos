"""A2A protocol module: TaskManager ABC, LocalTaskManager, JSON-RPC dispatcher, and route setup.

Provides:
- Task data model (TaskState, TaskStatus, TaskMessage, TaskEvent, Task, AutonomousConfig, TaskBudgets)
- TaskManager ABC: send_message, list_tasks, get_task, cancel_task, shutdown
- LocalTaskManager: in-process execution with internal dict storage and OTel
- NullTaskManager: no-op implementation
- JSON-RPC 2.0 models and error codes
- setup_a2a_routes(): Mounts A2A endpoints on a FastAPI app
"""

import asyncio
import uuid
import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import (
    Awaitable,
    Dict,
    Any,
    Optional,
    Union,
    Callable,
    List,
    Tuple,
)
from datetime import datetime, timezone
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from opentelemetry import trace as trace_api, metrics

from pais.telemetry import SERVICE_NAME, is_otel_enabled

logger = logging.getLogger(__name__)


# --- Task Data Model ---


class TaskState(str, Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"


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
class TaskEvent:
    """Append-only event log entry for task lifecycle tracking."""

    id: str
    type: str
    timestamp: str  # ISO 8601 UTC
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp,
            "data": self.data,
        }


# Event type constants (module-level strings, not enum — extensible)
EVENT_TASK_SUBMITTED = "task.submitted"
EVENT_TASK_WORKING = "task.working"
EVENT_TASK_COMPLETED = "task.completed"
EVENT_TASK_FAILED = "task.failed"
EVENT_TASK_CANCELED = "task.canceled"
EVENT_AUTONOMOUS_BUDGET_EXHAUSTED = "autonomous.budget.exhausted"


@dataclass
class AutonomousConfig:
    """Per-iteration config for CRD-activated autonomous execution.

    A value of 0 means unlimited (no limit enforced) for that budget.
    """

    goal: str = ""
    interval_seconds: int = 0
    max_iter_runtime_seconds: int = 60


@dataclass
class TaskBudgets:
    """Overall budget limits for A2A async task execution.

    A value of 0 means unlimited (no limit enforced) for that budget.
    """

    max_iterations: int = 10
    max_runtime_seconds: int = 300
    max_tool_calls: int = 50
    interval_seconds: int = 0


@dataclass
class Task:
    """A2A Task representing a unit of work with lifecycle tracking."""

    id: str
    session_id: str
    status: TaskStatus
    history: List[TaskMessage] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    events: List[TaskEvent] = field(default_factory=list)
    autonomous: bool = False
    output: str = ""

    def add_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> TaskEvent:
        """Create and append a TaskEvent with auto-generated id and timestamp."""
        event = TaskEvent(
            id=uuid.uuid4().hex[:12],
            type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data or {},
        )
        self.events.append(event)
        return event

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "status": self.status.to_dict(),
            "history": [m.to_dict() for m in self.history],
            "artifacts": self.artifacts,
            "metadata": self.metadata,
            "events": [e.to_dict() for e in self.events],
            "autonomous": self.autonomous,
            "output": self.output,
        }


# --- OTel Metrics ---

_task_counter: Optional[metrics.Counter] = None
_task_duration: Optional[metrics.Histogram] = None


def get_task_metrics() -> Tuple[Optional[metrics.Counter], Optional[metrics.Histogram]]:
    """Lazily initialize and return (task_counter, task_duration). (None, None) when disabled."""
    global _task_counter, _task_duration

    if not is_otel_enabled():
        return None, None

    if _task_counter is None:
        meter = metrics.get_meter(SERVICE_NAME)
        _task_counter = meter.create_counter(
            "kaos.tasks", description="Task lifecycle events", unit="1"
        )
        _task_duration = meter.create_histogram(
            "kaos.task.duration", description="Task execution duration", unit="ms"
        )

    return _task_counter, _task_duration


# --- TaskManager ABC ---

ProcessFn = Callable[[Union[str, List[Dict[str, str]]], str], Awaitable[Tuple[str, int]]]


class TaskManager(ABC):
    """ABC for A2A task lifecycle management.

    Implementations handle task creation, execution, and state management internally.
    The interface mirrors the Memory ABC pattern (LocalMemory/RedisMemory/NullMemory).
    """

    @abstractmethod
    async def send_message(
        self,
        text: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Submit a message and return a Task. Execution strategy is implementation-defined."""
        ...

    @abstractmethod
    async def submit_autonomous(
        self,
        goal: str,
        session_id: Optional[str] = None,
        budgets: Optional[TaskBudgets] = None,
        autonomous_config: Optional["AutonomousConfig"] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Submit an autonomous run. Returns Task immediately (may be in-progress).

        Args:
            goal: The objective for the autonomous run.
            session_id: Optional session ID (auto-generated if not provided).
            budgets: Overall budgets for async task mode (ignored in autonomous mode).
            autonomous_config: Per-iteration config for autonomous mode. If provided, runs
                in autonomous mode (no overall limits). If None, runs as async task.
            metadata: Optional metadata for the task.
        """
        ...

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID."""
        ...

    @abstractmethod
    async def list_tasks(self) -> List[Task]:
        """Return all retained tasks, newest first."""
        ...

    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Returns True if cancellation was initiated."""
        ...

    async def wait_for_completion(
        self, task_id: str, timeout: float = 60.0, poll_interval: float = 0.1
    ) -> Optional[Task]:
        """Wait for task to reach terminal state. Default returns current state."""
        return await self.get_task(task_id)

    async def shutdown(self) -> None:
        """Clean up resources."""
        pass


# --- LocalTaskManager ---


class LocalTaskManager(TaskManager):
    """In-process task manager with internal dict storage and synchronous execution.

    Encapsulates task creation, state management, execution via process_fn,
    and OTel instrumentation. process_fn(message, session_id) -> (response, tool_call_count).
    """

    def __init__(
        self,
        process_fn: ProcessFn,
        max_tasks: int = 10000,
        setup_fn: Optional[Callable[[], None]] = None,
    ):
        self._process_fn = process_fn
        self._setup_fn = setup_fn
        self._tasks: Dict[str, Task] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self.max_tasks = max_tasks
        logger.info(f"LocalTaskManager initialized: max_tasks={max_tasks}")

    async def send_message(
        self,
        text: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Create a task, execute inline, and return the completed task."""
        tracer = trace_api.get_tracer(SERVICE_NAME)
        task_counter, _ = get_task_metrics()

        with tracer.start_as_current_span(
            "kaos.task.submit",
            attributes={"task.session_id": session_id or ""},
        ):
            task = self._create_task(session_id, text, metadata)
            logger.info(f"Submitted task {task.id} for session {task.session_id}")

            if task_counter:
                task_counter.add(1, {"state": "submitted"})

        await self._execute_task(task.id, text)
        return task

    async def submit_autonomous(
        self,
        goal: str,
        session_id: Optional[str] = None,
        budgets: Optional[TaskBudgets] = None,
        autonomous_config: Optional[AutonomousConfig] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Submit an autonomous run. Spawns background task, returns immediately."""
        tracer = trace_api.get_tracer(SERVICE_NAME)
        task_counter, _ = get_task_metrics()
        is_autonomous = autonomous_config is not None

        with tracer.start_as_current_span(
            "kaos.task.submit_autonomous",
            attributes={
                "task.session_id": session_id or "",
                "task.autonomous": True,
            },
        ):
            task = self._create_task(session_id, goal, metadata)
            task.autonomous = True
            task.add_event(EVENT_TASK_SUBMITTED, {"goal_preview": goal[:200]})
            logger.info(f"Submitted autonomous task {task.id}")

            if task_counter:
                task_counter.add(1, {"state": "submitted", "autonomous": True})

        self._transition(task.id, TaskState.WORKING, "Autonomous execution started")
        task.add_event(EVENT_TASK_WORKING, {})

        effective_budgets = budgets or TaskBudgets()

        bg_task = asyncio.create_task(
            self._execute_autonomous(
                task.id,
                goal,
                task.session_id,
                budgets=effective_budgets,
                autonomous_config=autonomous_config,
            )
        )
        self._running_tasks[task.id] = bg_task
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    async def list_tasks(self) -> List[Task]:
        return sorted(
            list(self._tasks.values()),
            key=lambda task: task.status.timestamp,
            reverse=True,
        )

    async def cancel_task(self, task_id: str) -> bool:
        tracer = trace_api.get_tracer(SERVICE_NAME)
        task_counter, _ = get_task_metrics()

        with tracer.start_as_current_span(
            "kaos.task.cancel",
            attributes={"task.id": task_id},
        ):
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status.state in TERMINAL_STATES:
                return False
            if not self._transition(task_id, TaskState.CANCELED, "Canceled by request"):
                return False

            # Cancel background asyncio task if running
            bg = self._running_tasks.pop(task_id, None)
            if bg and not bg.done():
                bg.cancel()

            if task_counter:
                task_counter.add(1, {"state": "cancel_requested"})

            return True

    async def wait_for_completion(
        self, task_id: str, timeout: float = 60.0, poll_interval: float = 0.1
    ) -> Optional[Task]:
        """Wait for task to reach terminal state, polling at intervals."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self._tasks.get(task_id)
            if task and task.status.state in TERMINAL_STATES:
                return task
            await asyncio.sleep(poll_interval)
        return self._tasks.get(task_id)

    async def shutdown(self) -> None:
        """Cancel all running tasks and clean up."""
        for task_id, bg in list(self._running_tasks.items()):
            if not bg.done():
                bg.cancel()
        # Wait briefly for cancellations
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
            self._running_tasks.clear()
        logger.debug("LocalTaskManager shutdown")

    # --- Internal methods ---

    def _create_task(
        self,
        session_id: Optional[str],
        input_message: Optional[str],
        metadata: Optional[Dict[str, Any]],
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

        self._cleanup_if_needed()
        self._tasks[task_id] = task
        logger.debug(f"Created task {task_id} in session {session_id}")
        return task

    def _transition(self, task_id: str, state: TaskState, message: Optional[str] = None) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        current = task.status.state
        if state not in VALID_TRANSITIONS.get(current, set()):
            logger.warning(
                f"Invalid transition {current.value} -> {state.value} for task {task_id}"
            )
            return False
        task.status = TaskStatus(
            state=state,
            message=message,
            timestamp=datetime.now(timezone.utc),
        )
        logger.debug(f"Task {task_id}: {current.value} -> {state.value}")
        return True

    async def _execute_task(self, task_id: str, input_message: str) -> None:
        """Execute a task synchronously using process_fn."""
        if self._setup_fn:
            self._setup_fn()

        tracer = trace_api.get_tracer(SERVICE_NAME)
        task_counter, task_duration = get_task_metrics()
        start_time = time.perf_counter()

        with tracer.start_as_current_span(
            "kaos.task.execute",
            attributes={"task.id": task_id},
        ) as span:
            task = self._tasks.get(task_id)
            if not task:
                logger.error(f"Task {task_id} not found for execution")
                return

            if not self._transition(task_id, TaskState.WORKING, "Processing"):
                logger.error(f"Failed to transition task {task_id} to working")
                return

            try:
                response_content, _ = await self._process_fn(input_message, task.session_id)

                task.history.append(TaskMessage(role="agent", text=response_content))
                self._transition(task_id, TaskState.COMPLETED, "Done")
                logger.info(f"Task {task_id} completed")
                span.set_attribute("task.state", "completed")
                if task_counter:
                    task_counter.add(1, {"state": "completed"})

            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                self._transition(task_id, TaskState.FAILED, str(e))
                span.set_attribute("task.state", "failed")
                span.record_exception(e)
                if task_counter:
                    task_counter.add(1, {"state": "failed"})

            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000
                if task_duration:
                    task_duration.record(duration_ms, {"task.id": task_id})

    async def _execute_autonomous(
        self,
        task_id: str,
        goal: str,
        session_id: str,
        budgets: TaskBudgets,
        autonomous_config: Optional[AutonomousConfig] = None,
    ) -> None:
        """Execute autonomous loop: autonomous mode (forever) or async task (budget-limited).

        Autonomous mode (autonomous_config provided): runs forever, per-iteration time limit only.
        Async task mode (autonomous_config=None): overall budgets, "no tool calls = done" completion.
        """
        if self._setup_fn:
            self._setup_fn()

        tracer = trace_api.get_tracer(SERVICE_NAME)
        task_counter, task_duration = get_task_metrics()
        start_time = time.perf_counter()
        is_autonomous = autonomous_config is not None
        interval_seconds = (
            autonomous_config.interval_seconds if autonomous_config else budgets.interval_seconds
        )

        span_attrs: Dict[str, Any] = {
            "autonomous.task_id": task_id,
            "autonomous.session_id": session_id,
            "autonomous.is_autonomous": is_autonomous,
        }
        if not is_autonomous:
            span_attrs["autonomous.max_iterations"] = budgets.max_iterations
            span_attrs["autonomous.max_runtime_seconds"] = budgets.max_runtime_seconds
            span_attrs["autonomous.max_tool_calls"] = budgets.max_tool_calls
        if autonomous_config:
            span_attrs["autonomous.max_iter_runtime_seconds"] = (
                autonomous_config.max_iter_runtime_seconds
            )

        with tracer.start_as_current_span("kaos.autonomous.run", attributes=span_attrs) as span:
            task = self._tasks.get(task_id)
            if not task:
                logger.error(f"Autonomous task {task_id} not found")
                return

            try:
                iteration = 0
                total_tool_calls = 0
                loop_start = time.monotonic()
                last_response = ""

                while True:
                    # Check cancellation
                    current_task = self._tasks.get(task_id)
                    if current_task and current_task.status.state in TERMINAL_STATES:
                        logger.info(f"Autonomous run {task_id} stopped: task in terminal state")
                        break

                    # --- Async task budget checks (autonomous mode skips these) ---
                    if not is_autonomous:
                        if budgets.max_iterations > 0 and iteration >= budgets.max_iterations:
                            msg = f"Budget exhausted: max_iterations ({budgets.max_iterations}) reached"
                            logger.info(f"Autonomous run {task_id}: {msg}")
                            task.add_event(
                                EVENT_AUTONOMOUS_BUDGET_EXHAUSTED,
                                {"reason": "max_iterations", "iterations": iteration},
                            )
                            last_response = msg
                            break

                        elapsed = time.monotonic() - loop_start
                        if (
                            budgets.max_runtime_seconds > 0
                            and elapsed >= budgets.max_runtime_seconds
                        ):
                            msg = f"Budget exhausted: max_runtime_seconds ({budgets.max_runtime_seconds}s) reached"
                            logger.info(f"Autonomous run {task_id}: {msg}")
                            task.add_event(
                                EVENT_AUTONOMOUS_BUDGET_EXHAUSTED,
                                {"reason": "max_runtime_seconds", "elapsed": round(elapsed, 1)},
                            )
                            last_response = msg
                            break

                        if (
                            budgets.max_tool_calls > 0
                            and total_tool_calls >= budgets.max_tool_calls
                        ):
                            msg = f"Budget exhausted: max_tool_calls ({budgets.max_tool_calls}) reached"
                            logger.info(f"Autonomous run {task_id}: {msg}")
                            task.add_event(
                                EVENT_AUTONOMOUS_BUDGET_EXHAUSTED,
                                {"reason": "max_tool_calls", "total_tool_calls": total_tool_calls},
                            )
                            last_response = msg
                            break

                    # Build iteration message
                    if iteration == 0:
                        message = goal
                    elif is_autonomous:
                        message = (
                            f"Continue working toward the goal. This is iteration {iteration + 1}. "
                            "Review your progress and decide next steps."
                        )
                    else:
                        message = (
                            f"Continue working toward the goal. This is iteration {iteration + 1}. "
                            "Review your progress and decide next steps. If the goal is fully achieved, "
                            "respond with your final answer without making any tool calls."
                        )

                    # Run one iteration
                    with tracer.start_as_current_span(
                        "kaos.autonomous.iteration",
                        attributes={"autonomous.iteration": iteration},
                    ):
                        try:
                            iter_timeout = (
                                autonomous_config.max_iter_runtime_seconds
                                if is_autonomous
                                and autonomous_config
                                and autonomous_config.max_iter_runtime_seconds > 0
                                else 0
                            )
                            if iter_timeout > 0:
                                last_response, tool_call_count = await asyncio.wait_for(
                                    self._process_fn(message, session_id),
                                    timeout=iter_timeout,
                                )
                            else:
                                last_response, tool_call_count = await self._process_fn(
                                    message, session_id
                                )
                        except Exception as iter_err:
                            if is_autonomous:
                                err_type = type(iter_err).__name__
                                logger.warning(
                                    f"Autonomous iteration {iteration} failed ({err_type}): "
                                    f"{iter_err}, continuing after interval..."
                                )
                                iteration += 1
                                if interval_seconds > 0:
                                    await asyncio.sleep(interval_seconds)
                                continue
                            else:
                                raise

                    if tool_call_count > 0:
                        total_tool_calls += tool_call_count

                    iteration += 1

                    # Completion detection for async tasks: no tool calls = done
                    if not is_autonomous and tool_call_count == 0:
                        logger.info(
                            f"Autonomous run {task_id} completed after {iteration} iterations"
                        )
                        break

                    # Inter-iteration interval
                    if interval_seconds > 0:
                        await asyncio.sleep(interval_seconds)

                task.output = last_response
                task.history.append(TaskMessage(role="agent", text=last_response))
                current_state = self._tasks.get(task_id)
                if current_state and current_state.status.state not in TERMINAL_STATES:
                    self._transition(task_id, TaskState.COMPLETED, "Done")
                    task.add_event(
                        EVENT_TASK_COMPLETED,
                        {"output_preview": last_response[:200]},
                    )
                    logger.info(f"Autonomous task {task_id} completed")
                    span.set_attribute("task.state", "completed")
                    if task_counter:
                        task_counter.add(1, {"state": "completed", "autonomous": True})

            except asyncio.CancelledError:
                self._transition(task_id, TaskState.CANCELED, "Canceled")
                if task:
                    task.add_event(EVENT_TASK_CANCELED, {})
                logger.info(f"Autonomous task {task_id} canceled")
                span.set_attribute("task.state", "canceled")

            except Exception as e:
                logger.error(f"Autonomous task {task_id} failed: {e}")
                self._transition(task_id, TaskState.FAILED, str(e))
                if task:
                    task.add_event(EVENT_TASK_FAILED, {"error": str(e)})
                span.set_attribute("task.state", "failed")
                span.record_exception(e)
                if task_counter:
                    task_counter.add(1, {"state": "failed", "autonomous": True})

            finally:
                self._running_tasks.pop(task_id, None)
                duration_ms = (time.perf_counter() - start_time) * 1000
                if task_duration:
                    task_duration.record(duration_ms, {"task.id": task_id, "autonomous": True})

    def _cleanup_if_needed(self) -> None:
        if len(self._tasks) >= self.max_tasks:
            terminal = [
                (tid, t) for tid, t in self._tasks.items() if t.status.state in TERMINAL_STATES
            ]
            terminal.sort(key=lambda x: x[1].status.timestamp)
            to_remove = max(1, self.max_tasks // 10)
            for tid, _ in terminal[:to_remove]:
                del self._tasks[tid]
            logger.info(f"Cleaned up {min(to_remove, len(terminal))} old tasks")


# --- NullTaskManager ---


class NullTaskManager(TaskManager):
    """No-op task manager — all operations succeed silently."""

    def __init__(self):
        logger.info("NullTaskManager initialized (task management disabled)")

    async def send_message(
        self,
        text: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        task_id = f"null_task_{uuid.uuid4().hex[:8]}"
        return Task(
            id=task_id,
            session_id=session_id or "null-session",
            status=TaskStatus(state=TaskState.COMPLETED),
        )

    async def submit_autonomous(
        self,
        goal: str,
        session_id: Optional[str] = None,
        budgets: Optional[TaskBudgets] = None,
        autonomous_config: Optional[AutonomousConfig] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        task_id = f"null_task_{uuid.uuid4().hex[:8]}"
        return Task(
            id=task_id,
            session_id=session_id or "null-session",
            status=TaskStatus(state=TaskState.COMPLETED),
            autonomous=True,
        )

    async def get_task(self, task_id: str) -> Optional[Task]:
        return None

    async def list_tasks(self) -> List[Task]:
        return []

    async def cancel_task(self, task_id: str) -> bool:
        return False


# --- JSON-RPC 2.0 Models ---


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None
    id: Optional[Union[str, int]] = None

    def to_dict(self) -> dict:
        d: dict = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            d["error"] = self.error.model_dump()
        else:
            d["result"] = self.result
        return d


# JSON-RPC error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_TASK_NOT_FOUND = -32001


# --- JSON-RPC Dispatcher ---


async def _handle_jsonrpc(request: Request, task_manager: TaskManager) -> JSONResponse:
    """Dispatch JSON-RPC 2.0 requests for A2A task methods."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            JsonRpcResponse(
                error=JsonRpcError(code=JSONRPC_PARSE_ERROR, message="Parse error"),
            ).to_dict()
        )

    try:
        rpc_req = JsonRpcRequest(**body)
    except Exception:
        return JSONResponse(
            JsonRpcResponse(
                error=JsonRpcError(
                    code=JSONRPC_INVALID_REQUEST, message="Invalid JSON-RPC request"
                ),
            ).to_dict()
        )

    method = rpc_req.method
    params = rpc_req.params or {}
    rpc_id = rpc_req.id

    # A2A RC v1.0 PascalCase methods + legacy aliases
    if method in ("SendMessage", "tasks/send"):
        return await _jsonrpc_send_message(task_manager, params, rpc_id)
    elif method in ("GetTask", "tasks/get"):
        return await _jsonrpc_get_task(task_manager, params, rpc_id)
    elif method in ("ListTasks", "tasks/list"):
        return await _jsonrpc_list_tasks(task_manager, rpc_id)
    elif method in ("CancelTask", "tasks/cancel"):
        return await _jsonrpc_cancel_task(task_manager, params, rpc_id)
    else:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_METHOD_NOT_FOUND,
                    message=f"Method not found: {method}",
                ),
            ).to_dict()
        )


async def _jsonrpc_send_message(
    task_manager: TaskManager,
    params: Dict[str, Any],
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle SendMessage: create a task and optionally wait for completion.

    Supports A2A RC v1.0 SendMessageRequest format:
    - message: {role, parts} (required)
    - configuration: {blocking: bool} (optional, default false)
    - contextId: maps to session_id (optional)
    - sessionId: legacy alias for contextId (optional)
    """
    message = params.get("message")
    if not message:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Missing required 'message' parameter",
                ),
            ).to_dict()
        )

    parts = message.get("parts", [])
    text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    input_text = " ".join(text_parts) if text_parts else message.get("text", "")

    if not input_text:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Message must contain text content",
                ),
            ).to_dict()
        )

    # contextId (A2A spec) or sessionId (legacy)
    session_id = params.get("contextId") or params.get("sessionId")

    # Extract message metadata (e.g. delegation flag)
    message_metadata = message.get("metadata")
    task_metadata = dict(message_metadata) if isinstance(message_metadata, dict) else None

    # Check for autonomous mode
    config = params.get("configuration", {})
    mode = config.get("mode", "interactive")

    if mode == "autonomous":
        budgets_raw = config.get("budgets", {})
        budgets = TaskBudgets(
            max_iterations=budgets_raw.get("maxIterations", 10),
            max_runtime_seconds=budgets_raw.get("maxRuntimeSeconds", 300),
            max_tool_calls=budgets_raw.get("maxToolCalls", 50),
            interval_seconds=budgets_raw.get("intervalSeconds", 0),
        )
        task = await task_manager.submit_autonomous(
            goal=input_text,
            session_id=session_id,
            budgets=budgets,
            metadata=task_metadata,
        )
    else:
        task = await task_manager.send_message(
            input_text, session_id=session_id, metadata=task_metadata
        )

    return JSONResponse(JsonRpcResponse(id=rpc_id, result=task.to_dict()).to_dict())


async def _jsonrpc_get_task(
    task_manager: TaskManager,
    params: Dict[str, Any],
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle GetTask: retrieve task status."""
    task_id = params.get("id")
    if not task_id:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Missing required 'id' parameter",
                ),
            ).to_dict()
        )

    task = await task_manager.get_task(task_id)
    if not task:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            ).to_dict()
        )

    return JSONResponse(JsonRpcResponse(id=rpc_id, result=task.to_dict()).to_dict())


async def _jsonrpc_list_tasks(
    task_manager: TaskManager,
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle ListTasks: retrieve all retained task statuses."""
    tasks = await task_manager.list_tasks()
    result = {"tasks": [task.to_dict() for task in tasks], "count": len(tasks)}
    return JSONResponse(JsonRpcResponse(id=rpc_id, result=result).to_dict())


async def _jsonrpc_cancel_task(
    task_manager: TaskManager,
    params: Dict[str, Any],
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle CancelTask: cancel a running task."""
    task_id = params.get("id")
    if not task_id:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Missing required 'id' parameter",
                ),
            ).to_dict()
        )

    canceled = await task_manager.cancel_task(task_id)
    if not canceled:
        task = await task_manager.get_task(task_id)
        if not task:
            return JSONResponse(
                JsonRpcResponse(
                    id=rpc_id,
                    error=JsonRpcError(
                        code=JSONRPC_TASK_NOT_FOUND,
                        message=f"Task not found: {task_id}",
                    ),
                ).to_dict()
            )
        # Task exists but already terminal
        return JSONResponse(JsonRpcResponse(id=rpc_id, result=task.to_dict()).to_dict())

    task = await task_manager.get_task(task_id)
    return JSONResponse(
        JsonRpcResponse(id=rpc_id, result=task.to_dict() if task else None).to_dict()
    )


def setup_a2a_routes(app: FastAPI, task_manager: TaskManager) -> None:
    """Mount A2A JSON-RPC endpoint on a FastAPI app."""

    @app.post("/")
    async def jsonrpc_endpoint(request: Request):
        """A2A JSON-RPC 2.0 endpoint for task lifecycle management."""
        return await _handle_jsonrpc(request, task_manager)
