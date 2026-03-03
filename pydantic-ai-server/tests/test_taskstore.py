"""Tests for TaskStore data model, LocalTaskStore, and NullTaskStore."""

import pytest

from pais.taskstore import (
    TaskState,
    TaskStatus,
    TaskMessage,
    Task,
    LocalTaskStore,
    NullTaskStore,
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


class TestLocalTaskStore:
    """Tests for LocalTaskStore CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_task(self):
        store = LocalTaskStore()
        task = await store.create_task(input_message="Hello")
        assert task.id.startswith("task_")
        assert task.session_id.startswith("session_")
        assert task.status.state == TaskState.SUBMITTED
        assert len(task.history) == 1
        assert task.history[0].role == "user"
        assert task.history[0].text == "Hello"

    @pytest.mark.asyncio
    async def test_create_task_with_session_id(self):
        store = LocalTaskStore()
        task = await store.create_task(session_id="my-session", input_message="Hello")
        assert task.session_id == "my-session"

    @pytest.mark.asyncio
    async def test_create_task_with_metadata(self):
        store = LocalTaskStore()
        task = await store.create_task(metadata={"priority": "high"})
        assert task.metadata == {"priority": "high"}

    @pytest.mark.asyncio
    async def test_create_task_no_input(self):
        store = LocalTaskStore()
        task = await store.create_task()
        assert len(task.history) == 0

    @pytest.mark.asyncio
    async def test_get_task(self):
        store = LocalTaskStore()
        created = await store.create_task(input_message="Test")
        fetched = await store.get_task(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        store = LocalTaskStore()
        result = await store.get_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_task_state(self):
        store = LocalTaskStore()
        task = await store.create_task()

        updated = await store.update_task_state(task.id, TaskState.WORKING, "Processing")
        assert updated is not None
        assert updated.status.state == TaskState.WORKING
        assert updated.status.message == "Processing"

    @pytest.mark.asyncio
    async def test_update_task_state_invalid_transition(self):
        store = LocalTaskStore()
        task = await store.create_task()

        # submitted -> completed is not valid (must go through working)
        result = await store.update_task_state(task.id, TaskState.COMPLETED)
        assert result is None
        # State unchanged
        fetched = await store.get_task(task.id)
        assert fetched is not None
        assert fetched.status.state == TaskState.SUBMITTED

    @pytest.mark.asyncio
    async def test_update_task_state_not_found(self):
        store = LocalTaskStore()
        result = await store.update_task_state("nonexistent", TaskState.WORKING)
        assert result is None

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        store = LocalTaskStore()
        task = await store.create_task(input_message="Do work")
        assert task.status.state == TaskState.SUBMITTED

        await store.update_task_state(task.id, TaskState.WORKING, "In progress")
        fetched = await store.get_task(task.id)
        assert fetched is not None
        assert fetched.status.state == TaskState.WORKING

        await store.set_task_output(fetched.id, "Work done!")
        await store.update_task_state(fetched.id, TaskState.COMPLETED, "Finished")
        completed = await store.get_task(fetched.id)
        assert completed is not None
        assert completed.status.state == TaskState.COMPLETED
        assert len(completed.history) == 2
        assert completed.history[1].role == "agent"
        assert completed.history[1].text == "Work done!"

    @pytest.mark.asyncio
    async def test_cancel_task(self):
        store = LocalTaskStore()
        task = await store.create_task()
        result = await store.cancel_task(task.id)
        assert result is not None
        assert result.status.state == TaskState.CANCELED

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self):
        store = LocalTaskStore()
        task = await store.create_task()
        await store.update_task_state(task.id, TaskState.WORKING)
        await store.update_task_state(task.id, TaskState.COMPLETED)
        result = await store.cancel_task(task.id)
        assert result is None  # Cannot cancel completed task

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        store = LocalTaskStore()
        result = await store.cancel_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        store = LocalTaskStore()
        await store.create_task(session_id="s1")
        await store.create_task(session_id="s1")
        await store.create_task(session_id="s2")

        all_tasks = await store.list_tasks()
        assert len(all_tasks) == 3

        s1_tasks = await store.list_tasks(session_id="s1")
        assert len(s1_tasks) == 2

        s2_tasks = await store.list_tasks(session_id="s2")
        assert len(s2_tasks) == 1

    @pytest.mark.asyncio
    async def test_set_task_output(self):
        store = LocalTaskStore()
        task = await store.create_task(input_message="Hello")
        result = await store.set_task_output(task.id, "Response text")
        assert result is not None
        assert len(result.history) == 2
        assert result.history[1].text == "Response text"

    @pytest.mark.asyncio
    async def test_set_task_output_not_found(self):
        store = LocalTaskStore()
        result = await store.set_task_output("nonexistent", "text")
        assert result is None

    @pytest.mark.asyncio
    async def test_failed_task_lifecycle(self):
        store = LocalTaskStore()
        task = await store.create_task()
        await store.update_task_state(task.id, TaskState.WORKING)
        await store.update_task_state(task.id, TaskState.FAILED, "Error occurred")
        fetched = await store.get_task(task.id)
        assert fetched is not None
        assert fetched.status.state == TaskState.FAILED
        assert fetched.status.message == "Error occurred"

    @pytest.mark.asyncio
    async def test_terminal_state_no_transitions(self):
        """Terminal states cannot transition to any other state."""
        store = LocalTaskStore()
        task = await store.create_task()
        await store.update_task_state(task.id, TaskState.WORKING)
        await store.update_task_state(task.id, TaskState.COMPLETED)

        for target in TaskState:
            result = await store.update_task_state(task.id, target)
            assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_on_capacity(self):
        store = LocalTaskStore(max_tasks=5)
        tasks = []
        for i in range(5):
            t = await store.create_task()
            tasks.append(t)

        # Mark first 2 as completed
        await store.update_task_state(tasks[0].id, TaskState.WORKING)
        await store.update_task_state(tasks[0].id, TaskState.COMPLETED)
        await store.update_task_state(tasks[1].id, TaskState.WORKING)
        await store.update_task_state(tasks[1].id, TaskState.COMPLETED)

        # Creating 6th triggers cleanup
        await store.create_task()
        all_tasks = await store.list_tasks()
        assert len(all_tasks) <= 5


class TestNullTaskStore:
    """Tests for NullTaskStore no-op implementation."""

    @pytest.mark.asyncio
    async def test_create_task(self):
        store = NullTaskStore()
        task = await store.create_task(input_message="Hello")
        assert task.id.startswith("null_task_")
        assert task.status.state == TaskState.SUBMITTED

    @pytest.mark.asyncio
    async def test_get_task_returns_none(self):
        store = NullTaskStore()
        assert await store.get_task("any-id") is None

    @pytest.mark.asyncio
    async def test_update_returns_none(self):
        store = NullTaskStore()
        assert await store.update_task_state("any", TaskState.WORKING) is None

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self):
        store = NullTaskStore()
        assert await store.cancel_task("any") is None

    @pytest.mark.asyncio
    async def test_list_returns_empty(self):
        store = NullTaskStore()
        assert await store.list_tasks() == []

    @pytest.mark.asyncio
    async def test_set_output_returns_none(self):
        store = NullTaskStore()
        assert await store.set_task_output("any", "text") is None

    @pytest.mark.asyncio
    async def test_close(self):
        store = NullTaskStore()
        await store.close()  # Should not raise
