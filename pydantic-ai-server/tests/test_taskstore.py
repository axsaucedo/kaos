"""Tests for Task data model, LocalTaskManager, and NullTaskManager."""

import pytest

from pais.a2a import (
    TaskState,
    TaskStatus,
    TaskMessage,
    TaskEvent,
    Task,
    AutonomousBudgets,
    LocalTaskManager,
    NullTaskManager,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    EVENT_TASK_SUBMITTED,
    EVENT_TASK_COMPLETED,
    EVENT_AUTONOMOUS_ITERATION_STARTED,
    EVENT_AUTONOMOUS_BUDGET_EXHAUSTED,
)


class TestTaskModel:
    """Tests for Task data model and serialization."""

    def test_task_state_values(self):
        assert TaskState.SUBMITTED.value == "submitted"
        assert TaskState.WORKING.value == "working"
        assert TaskState.COMPLETED.value == "completed"
        assert TaskState.FAILED.value == "failed"
        assert TaskState.CANCELED.value == "canceled"
        assert TaskState.INPUT_REQUIRED.value == "input-required"

    def test_task_status_to_dict(self):
        status = TaskStatus(state=TaskState.SUBMITTED, message="Starting")
        d = status.to_dict()
        assert d["state"] == "submitted"
        assert d["message"] == "Starting"
        assert "timestamp" in d

    def test_task_status_to_dict_no_message(self):
        status = TaskStatus(state=TaskState.WORKING)
        d = status.to_dict()
        assert d["state"] == "working"
        assert "message" not in d

    def test_task_message_to_dict(self):
        msg = TaskMessage(role="user", text="Hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["parts"] == [{"type": "text", "text": "Hello"}]

    def test_task_to_dict(self):
        task = Task(
            id="task_123",
            session_id="session_456",
            status=TaskStatus(state=TaskState.SUBMITTED),
            history=[TaskMessage(role="user", text="Do something")],
            metadata={"key": "value"},
        )
        d = task.to_dict()
        assert d["id"] == "task_123"
        assert d["sessionId"] == "session_456"
        assert d["status"]["state"] == "submitted"
        assert len(d["history"]) == 1
        assert d["history"][0]["role"] == "user"
        assert d["metadata"] == {"key": "value"}

    def test_terminal_states(self):
        assert TaskState.COMPLETED in TERMINAL_STATES
        assert TaskState.FAILED in TERMINAL_STATES
        assert TaskState.CANCELED in TERMINAL_STATES
        assert TaskState.SUBMITTED not in TERMINAL_STATES
        assert TaskState.WORKING not in TERMINAL_STATES

    def test_valid_transitions(self):
        assert TaskState.WORKING in VALID_TRANSITIONS[TaskState.SUBMITTED]
        assert TaskState.CANCELED in VALID_TRANSITIONS[TaskState.SUBMITTED]
        assert TaskState.COMPLETED in VALID_TRANSITIONS[TaskState.WORKING]
        assert TaskState.FAILED in VALID_TRANSITIONS[TaskState.WORKING]
        assert len(VALID_TRANSITIONS[TaskState.COMPLETED]) == 0
        assert len(VALID_TRANSITIONS[TaskState.FAILED]) == 0
        assert len(VALID_TRANSITIONS[TaskState.CANCELED]) == 0


class TestTaskEvent:
    """Tests for TaskEvent dataclass and Task.add_event()."""

    def test_task_event_creation(self):
        event = TaskEvent(
            id="evt_001", type="task.submitted", timestamp="2024-01-01T00:00:00+00:00"
        )
        assert event.id == "evt_001"
        assert event.type == "task.submitted"
        assert event.data == {}

    def test_task_event_with_data(self):
        event = TaskEvent(
            id="evt_002",
            type="autonomous.iteration.started",
            timestamp="2024-01-01T00:00:00+00:00",
            data={"iteration": 1},
        )
        assert event.data == {"iteration": 1}

    def test_task_event_to_dict(self):
        event = TaskEvent(
            id="evt_003",
            type="task.completed",
            timestamp="2024-01-01T00:00:00+00:00",
            data={"output_preview": "Done"},
        )
        d = event.to_dict()
        assert d["id"] == "evt_003"
        assert d["type"] == "task.completed"
        assert d["timestamp"] == "2024-01-01T00:00:00+00:00"
        assert d["data"] == {"output_preview": "Done"}

    def test_task_add_event(self):
        task = Task(
            id="task_123",
            session_id="s1",
            status=TaskStatus(state=TaskState.SUBMITTED),
        )
        event = task.add_event(EVENT_TASK_SUBMITTED, {"trigger": "api"})
        assert len(task.events) == 1
        assert event.type == EVENT_TASK_SUBMITTED
        assert event.data == {"trigger": "api"}
        assert len(event.id) == 12  # uuid hex[:12]
        assert "T" in event.timestamp  # ISO format

    def test_task_add_event_ordering(self):
        task = Task(
            id="task_123",
            session_id="s1",
            status=TaskStatus(state=TaskState.SUBMITTED),
        )
        task.add_event(EVENT_TASK_SUBMITTED)
        task.add_event(EVENT_AUTONOMOUS_ITERATION_STARTED, {"iteration": 0})
        task.add_event(EVENT_TASK_COMPLETED)
        assert len(task.events) == 3
        assert task.events[0].type == EVENT_TASK_SUBMITTED
        assert task.events[1].type == EVENT_AUTONOMOUS_ITERATION_STARTED
        assert task.events[2].type == EVENT_TASK_COMPLETED

    def test_task_add_event_no_data(self):
        task = Task(
            id="task_123",
            session_id="s1",
            status=TaskStatus(state=TaskState.SUBMITTED),
        )
        event = task.add_event(EVENT_TASK_SUBMITTED)
        assert event.data == {}


class TestAutonomousBudgets:
    """Tests for AutonomousBudgets dataclass."""

    def test_defaults(self):
        budgets = AutonomousBudgets()
        assert budgets.max_iterations == 10
        assert budgets.max_runtime_seconds == 300
        assert budgets.max_tool_calls == 50
        assert budgets.interval_seconds == 0

    def test_custom_values(self):
        budgets = AutonomousBudgets(
            max_iterations=5, max_runtime_seconds=60, max_tool_calls=20, interval_seconds=10
        )
        assert budgets.max_iterations == 5
        assert budgets.max_runtime_seconds == 60
        assert budgets.max_tool_calls == 20
        assert budgets.interval_seconds == 10


class TestTaskExtendedFields:
    """Tests for Task mode, output, and events fields."""

    def test_task_default_mode(self):
        task = Task(
            id="t1",
            session_id="s1",
            status=TaskStatus(state=TaskState.SUBMITTED),
        )
        assert task.mode == "interactive"
        assert task.output == ""
        assert task.events == []

    def test_task_autonomous_mode(self):
        task = Task(
            id="t1",
            session_id="s1",
            status=TaskStatus(state=TaskState.SUBMITTED),
            mode="autonomous",
        )
        assert task.mode == "autonomous"

    def test_task_to_dict_includes_new_fields(self):
        task = Task(
            id="t1",
            session_id="s1",
            status=TaskStatus(state=TaskState.COMPLETED),
            mode="autonomous",
            output="Final report",
        )
        task.add_event(EVENT_TASK_SUBMITTED)
        task.add_event(EVENT_TASK_COMPLETED, {"output_preview": "Final"})

        d = task.to_dict()
        assert d["mode"] == "autonomous"
        assert d["output"] == "Final report"
        assert len(d["events"]) == 2
        assert d["events"][0]["type"] == EVENT_TASK_SUBMITTED
        assert d["events"][1]["type"] == EVENT_TASK_COMPLETED
        assert d["events"][1]["data"]["output_preview"] == "Final"

    def test_task_to_dict_empty_events(self):
        task = Task(
            id="t1",
            session_id="s1",
            status=TaskStatus(state=TaskState.SUBMITTED),
        )
        d = task.to_dict()
        assert d["events"] == []
        assert d["mode"] == "interactive"
        assert d["output"] == ""


async def _mock_process(msg, session_id=""):
    """Simple mock process function that returns (response, tool_call_count)."""
    return ("Task result", 0)


class TestLocalTaskManager:
    """Tests for LocalTaskManager through the TaskManager interface."""

    @pytest.mark.asyncio
    async def test_send_message_creates_task(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Hello")
        assert task.id.startswith("task_")
        assert task.session_id.startswith("session_")
        assert task.status.state == TaskState.COMPLETED
        assert len(task.history) == 2
        assert task.history[0].role == "user"
        assert task.history[0].text == "Hello"
        assert task.history[1].role == "agent"

    @pytest.mark.asyncio
    async def test_send_message_with_session_id(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Hello", session_id="my-session")
        assert task.session_id == "my-session"

    @pytest.mark.asyncio
    async def test_send_message_with_metadata(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Hello", metadata={"priority": "high"})
        assert task.metadata == {"priority": "high"}

    @pytest.mark.asyncio
    async def test_send_message_generates_session_id(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Hello")
        assert task.session_id.startswith("session_")

    @pytest.mark.asyncio
    async def test_get_task(self):
        manager = LocalTaskManager(_mock_process)
        created = await manager.send_message("Test")
        fetched = await manager.get_task(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        manager = LocalTaskManager(_mock_process)
        result = await manager.get_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Do work")
        # Synchronous execution: task is completed immediately
        assert task.status.state == TaskState.COMPLETED
        assert len(task.history) >= 2
        assert task.history[1].role == "agent"
        assert task.history[1].text == "Task result"

    @pytest.mark.asyncio
    async def test_cancel_completed_task_not_possible(self):
        """Test that canceling a completed task returns False (sync execution completes immediately)."""
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Cancel me")
        # Task is already completed due to synchronous execution
        assert task.status.state == TaskState.COMPLETED
        result = await manager.cancel_task(task.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Complete me")
        assert task.status.state == TaskState.COMPLETED
        result = await manager.cancel_task(task.id)
        assert result is False  # Cannot cancel completed task

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        manager = LocalTaskManager(_mock_process)
        result = await manager.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_failed_task_lifecycle(self):
        async def failing_process(msg, session_id=""):
            raise RuntimeError("Error occurred")

        manager = LocalTaskManager(failing_process)
        task = await manager.send_message("Fail me")
        assert task.status.state == TaskState.FAILED
        assert task.status.message == "Error occurred"

    @pytest.mark.asyncio
    async def test_shutdown(self):
        manager = LocalTaskManager(_mock_process)
        await manager.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_on_capacity(self):
        manager = LocalTaskManager(_mock_process, max_tasks=5)
        for i in range(5):
            await manager.send_message(f"Task {i}")

        # Creating 6th triggers cleanup of completed tasks
        await manager.send_message("Task 5")
        # We just verify no errors occurred

    @pytest.mark.asyncio
    async def test_multiple_tasks(self):
        manager = LocalTaskManager(_mock_process)
        tasks = []
        for i in range(3):
            task = await manager.send_message(f"Task {i}", session_id=f"s{i}")
            tasks.append(task)

        for task in tasks:
            assert task.status.state == TaskState.COMPLETED


class TestLocalTaskManagerAutonomous:
    """Tests for LocalTaskManager.submit_autonomous with integrated loop."""

    @pytest.mark.asyncio
    async def test_submit_autonomous_creates_task(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.submit_autonomous("Analyze data")
        assert task.mode == "autonomous"
        assert task.status.state in {TaskState.WORKING, TaskState.COMPLETED}

    @pytest.mark.asyncio
    async def test_submit_autonomous_executes_to_completion(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.submit_autonomous("Run analysis")
        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.status.state == TaskState.COMPLETED
        assert completed.output is not None
        assert "Task result" in completed.output

    @pytest.mark.asyncio
    async def test_submit_autonomous_failure_handling(self):
        async def failing_process(msg, session_id):
            raise RuntimeError("Analysis failed")

        manager = LocalTaskManager(failing_process)
        task = await manager.submit_autonomous("Fail task")
        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.status.state == TaskState.FAILED
        assert completed.status.message is not None
        assert "Analysis failed" in completed.status.message

    @pytest.mark.asyncio
    async def test_submit_autonomous_events(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.submit_autonomous("Test events")
        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        event_types = [e.type for e in completed.events]
        assert EVENT_TASK_SUBMITTED in event_types
        assert EVENT_AUTONOMOUS_ITERATION_STARTED in event_types
        assert EVENT_TASK_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_submit_autonomous_budget_exhaustion(self):
        call_count = 0

        async def tool_calling_process(msg, session_id):
            nonlocal call_count
            call_count += 1
            return (f"Iteration {call_count}", 1)

        manager = LocalTaskManager(tool_calling_process)
        task = await manager.submit_autonomous(
            "Keep going", budgets=AutonomousBudgets(max_iterations=2)
        )
        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.status.state == TaskState.COMPLETED
        event_types = [e.type for e in completed.events]
        assert EVENT_AUTONOMOUS_BUDGET_EXHAUSTED in event_types

    @pytest.mark.asyncio
    async def test_shutdown_cancels_running_autonomous(self):
        import asyncio

        async def slow_process(msg, session_id):
            await asyncio.sleep(10)
            return ("Should not reach", 0)

        manager = LocalTaskManager(slow_process)
        task = await manager.submit_autonomous("Long task")
        assert task.id in manager._running_tasks
        await manager.shutdown()
        assert len(manager._running_tasks) == 0


class TestNullTaskManager:
    """Tests for NullTaskManager no-op implementation."""

    @pytest.mark.asyncio
    async def test_send_message(self):
        manager = NullTaskManager()
        task = await manager.send_message("Hello")
        assert task.id.startswith("null_task_")
        assert task.status.state == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_submit_autonomous(self):
        manager = NullTaskManager()
        task = await manager.submit_autonomous("Do something")
        assert task.id.startswith("null_task_")
        assert task.status.state == TaskState.COMPLETED
        assert task.mode == "autonomous"

    @pytest.mark.asyncio
    async def test_get_task_returns_none(self):
        manager = NullTaskManager()
        assert await manager.get_task("any-id") is None

    @pytest.mark.asyncio
    async def test_cancel_returns_false(self):
        manager = NullTaskManager()
        assert await manager.cancel_task("any") is False

    @pytest.mark.asyncio
    async def test_shutdown(self):
        manager = NullTaskManager()
        await manager.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_wait_for_completion_returns_none(self):
        manager = NullTaskManager()
        result = await manager.wait_for_completion("any-id", timeout=0.1)
        assert result is None
