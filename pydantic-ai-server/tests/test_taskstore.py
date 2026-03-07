"""Tests for Task data model, LocalTaskManager, and NullTaskManager."""

import asyncio
import pytest

from pais.a2a import (
    TaskState,
    TaskStatus,
    TaskMessage,
    Task,
    LocalTaskManager,
    NullTaskManager,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
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


async def _mock_process(msg, session_id="", stream=False):
    """Simple mock process function that yields a result."""
    yield "Task result"


class TestLocalTaskManager:
    """Tests for LocalTaskManager through the TaskManager interface."""

    @pytest.mark.asyncio
    async def test_send_message_creates_task(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Hello")
        assert task.id.startswith("task_")
        assert task.session_id.startswith("session_")
        assert task.status.state == TaskState.SUBMITTED
        assert len(task.history) == 1
        assert task.history[0].role == "user"
        assert task.history[0].text == "Hello"

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
        assert task.status.state == TaskState.SUBMITTED

        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.status.state == TaskState.COMPLETED
        assert len(completed.history) >= 2
        assert completed.history[1].role == "agent"
        assert completed.history[1].text == "Task result"

    @pytest.mark.asyncio
    async def test_cancel_task(self):
        """Test canceling a task that is still in submitted state."""
        started = asyncio.Event()

        async def slow_process(msg, session_id="", stream=False):
            started.set()
            await asyncio.sleep(100)
            yield "result"

        manager = LocalTaskManager(slow_process)
        task = await manager.send_message("Cancel me")

        # Wait for execution to start so the task is in working state
        await asyncio.wait_for(started.wait(), timeout=5.0)

        result = await manager.cancel_task(task.id)
        assert result is True

        fetched = await manager.get_task(task.id)
        assert fetched is not None
        assert fetched.status.state == TaskState.CANCELED
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self):
        manager = LocalTaskManager(_mock_process)
        task = await manager.send_message("Complete me")
        await manager.wait_for_completion(task.id, timeout=5.0)
        result = await manager.cancel_task(task.id)
        assert result is False  # Cannot cancel completed task

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        manager = LocalTaskManager(_mock_process)
        result = await manager.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_failed_task_lifecycle(self):
        async def failing_process(msg, session_id="", stream=False):
            raise RuntimeError("Error occurred")
            yield

        manager = LocalTaskManager(failing_process)
        task = await manager.send_message("Fail me")
        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.status.state == TaskState.FAILED
        assert completed.status.message == "Error occurred"

    @pytest.mark.asyncio
    async def test_shutdown(self):
        manager = LocalTaskManager(_mock_process)
        await manager.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_on_capacity(self):
        manager = LocalTaskManager(_mock_process, max_tasks=5)
        for i in range(5):
            task = await manager.send_message(f"Task {i}")
            await manager.wait_for_completion(task.id, timeout=5.0)

        # Creating 6th triggers cleanup of completed tasks
        await manager.send_message("Task 5")
        # Internal tasks dict should have been cleaned
        # We just verify no errors occurred

    @pytest.mark.asyncio
    async def test_multiple_tasks(self):
        manager = LocalTaskManager(_mock_process)
        tasks = []
        for i in range(3):
            task = await manager.send_message(f"Task {i}", session_id=f"s{i}")
            tasks.append(task)

        for task in tasks:
            completed = await manager.wait_for_completion(task.id, timeout=5.0)
            assert completed is not None
            assert completed.status.state == TaskState.COMPLETED


class TestNullTaskManager:
    """Tests for NullTaskManager no-op implementation."""

    @pytest.mark.asyncio
    async def test_send_message(self):
        manager = NullTaskManager()
        task = await manager.send_message("Hello")
        assert task.id.startswith("null_task_")
        assert task.status.state == TaskState.SUBMITTED

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
