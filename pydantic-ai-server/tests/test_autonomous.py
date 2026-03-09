"""Tests for autonomous execution loop (_run_autonomous)."""

import json
import os
import uuid
import pytest
from datetime import datetime, timezone

from pais.a2a import (
    Task,
    TaskState,
    TaskStatus,
    AutonomousBudgets,
    LocalTaskManager,
    EVENT_AUTONOMOUS_ITERATION_STARTED,
    EVENT_AUTONOMOUS_ITERATION_COMPLETED,
    EVENT_AUTONOMOUS_BUDGET_EXHAUSTED,
)
from tests.helpers import make_test_server


def _set_mock_responses(responses):
    """Set DEBUG_MOCK_RESPONSES env var for test."""
    os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(responses)


def _clear_mock_responses():
    os.environ.pop("DEBUG_MOCK_RESPONSES", None)


def _create_working_task(manager: LocalTaskManager) -> Task:
    """Create a task in WORKING state without consuming mock responses."""
    task = manager._create_task(
        session_id=f"session_{uuid.uuid4().hex[:8]}",
        input_message=None,
        metadata={"trigger": "test"},
    )
    manager._transition(task.id, TaskState.WORKING)
    return task


def _make_autonomous_server():
    """Create a test server with a dummy echo tool for autonomous tests."""
    server = make_test_server(task_manager_type="local")

    @server._agent.tool_plain
    def echo(message: str) -> str:
        """Echo the message back."""
        return f"Echo: {message}"

    # Populate mock responses once, then disable reset so autonomous iterations
    # consume responses cumulatively across _process_message calls
    if server._mock_state:
        server._mock_state.reset()
        server._mock_state = None

    return server


class TestAutonomousLoop:
    """Tests for AgentServer._run_autonomous()."""

    def setup_method(self):
        _clear_mock_responses()

    def teardown_method(self):
        _clear_mock_responses()

    @pytest.mark.asyncio
    async def test_single_iteration_no_tools(self):
        """Agent responds with pure text (no tools) — loop terminates after 1 iteration."""
        _set_mock_responses(["The goal is achieved."])
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=10)

        task = _create_working_task(server.task_manager)
        result = await server._run_autonomous("Analyze the data", task.session_id, budgets, task.id)

        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_budget_max_iterations(self):
        """Loop stops when max_iterations budget is exhausted."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "iter1"}}]}',
                "Still working on it.",
                '{"tool_calls": [{"id": "c2", "name": "echo", "arguments": {"message": "iter2"}}]}',
                "Still going.",
                '{"tool_calls": [{"id": "c3", "name": "echo", "arguments": {"message": "iter3"}}]}',
                "More work.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=2, max_tool_calls=100)

        task = _create_working_task(server.task_manager)
        result = await server._run_autonomous("Process all data", task.session_id, budgets, task.id)

        assert "budget exhausted" in result.lower()
        assert "max_iterations" in result.lower()

    @pytest.mark.asyncio
    async def test_budget_max_tool_calls(self):
        """Loop stops when max_tool_calls budget is exhausted."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "call1"}}]}',
                "Need more work.",
                '{"tool_calls": [{"id": "c2", "name": "echo", "arguments": {"message": "call2"}}]}',
                "Still going.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=100, max_tool_calls=1, max_runtime_seconds=300)

        task = _create_working_task(server.task_manager)
        result = await server._run_autonomous("Scan everything", task.session_id, budgets, task.id)

        assert "budget exhausted" in result.lower()
        assert "max_tool_calls" in result.lower()

    @pytest.mark.asyncio
    async def test_events_emitted(self):
        """Verify task events are emitted during autonomous execution."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "work"}}]}',
                "Still working.",
                "All done, here is the final report.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=10)

        task = _create_working_task(server.task_manager)
        await server._run_autonomous("Complete the task", task.session_id, budgets, task.id)

        task = await server.task_manager.get_task(task.id)
        assert task is not None

        event_types = [e.type for e in task.events]
        assert EVENT_AUTONOMOUS_ITERATION_STARTED in event_types
        assert EVENT_AUTONOMOUS_ITERATION_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_completion_detection(self):
        """Agent with no tool calls on first iteration = immediate completion."""
        _set_mock_responses(["Task is already done, no action needed."])
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=5)

        task = _create_working_task(server.task_manager)
        result = await server._run_autonomous("Check status", task.session_id, budgets, task.id)

        assert len(result) > 0

        task = await server.task_manager.get_task(task.id)
        assert task is not None
        started = [e for e in task.events if e.type == EVENT_AUTONOMOUS_ITERATION_STARTED]
        completed = [e for e in task.events if e.type == EVENT_AUTONOMOUS_ITERATION_COMPLETED]
        assert len(started) == 1
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_multi_iteration_then_completion(self):
        """Agent makes tool calls for 2 iterations, then completes with text on 3rd."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "step1"}}]}',
                "Step 1 done, need step 2.",
                '{"tool_calls": [{"id": "c2", "name": "echo", "arguments": {"message": "step2"}}]}',
                "Step 2 done, need final check.",
                "All steps complete. Final report: everything is working.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=10)

        task = _create_working_task(server.task_manager)
        result = await server._run_autonomous("Run all steps", task.session_id, budgets, task.id)

        assert "final report" in result.lower() or "complete" in result.lower()

        task = await server.task_manager.get_task(task.id)
        assert task is not None
        started = [e for e in task.events if e.type == EVENT_AUTONOMOUS_ITERATION_STARTED]
        assert len(started) == 3

    @pytest.mark.asyncio
    async def test_budget_exhausted_event(self):
        """Verify budget exhaustion emits the correct event."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "work"}}]}',
                "Need more.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=1)

        task = _create_working_task(server.task_manager)
        await server._run_autonomous("Infinite task", task.session_id, budgets, task.id)

        task = await server.task_manager.get_task(task.id)
        assert task is not None
        budget_events = [e for e in task.events if e.type == EVENT_AUTONOMOUS_BUDGET_EXHAUSTED]
        assert len(budget_events) == 1
        assert budget_events[0].data["reason"] == "max_iterations"
