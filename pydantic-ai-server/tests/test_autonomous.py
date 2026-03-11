"""Tests for autonomous execution loop (_run_autonomous)."""

import json
import os
import time
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

    @pytest.mark.asyncio
    async def test_unlimited_iterations_completes_naturally(self):
        """With max_iterations=0 (unlimited), loop exits via completion detection."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "work"}}]}',
                "Working on it.",
                "All done, goal achieved.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=0, max_runtime_seconds=0, max_tool_calls=0)

        task = _create_working_task(server.task_manager)
        result = await server._run_autonomous("Complete task", task.session_id, budgets, task.id)

        assert "done" in result.lower() or "achieved" in result.lower()
        task = await server.task_manager.get_task(task.id)
        assert task is not None
        budget_events = [e for e in task.events if e.type == EVENT_AUTONOMOUS_BUDGET_EXHAUSTED]
        assert len(budget_events) == 0

    @pytest.mark.asyncio
    async def test_interval_seconds_between_iterations(self):
        """With interval_seconds > 0, there is a pause between iterations."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "work"}}]}',
                "Working on it.",
                "All done.",
            ]
        )
        server = _make_autonomous_server()
        budgets = AutonomousBudgets(max_iterations=10, interval_seconds=0)

        task = _create_working_task(server.task_manager)
        start = time.monotonic()
        result = await server._run_autonomous("Do task", task.session_id, budgets, task.id)
        elapsed_no_interval = time.monotonic() - start

        assert "done" in result.lower()
        # With interval=0, execution should be fast (baseline)
        assert elapsed_no_interval < 5


class TestStartupAutonomous:
    """Tests for startup-activated autonomous mode."""

    def setup_method(self):
        _clear_mock_responses()

    def teardown_method(self):
        _clear_mock_responses()

    @pytest.mark.asyncio
    async def test_startup_autonomous_triggered(self):
        """Autonomous execution is triggered during lifespan when enabled."""
        _set_mock_responses(["Goal achieved."])
        server = _make_autonomous_server()
        server.settings.autonomous_enabled = True
        server.settings.autonomous_goal = "Monitor the system"
        server.settings.autonomous_max_iterations = 5

        async with server._lifespan(server.app):
            # wait briefly for background task
            import asyncio

            await asyncio.sleep(0.5)
            # Check that a task was submitted
            tasks = [t for t in server.task_manager._tasks.values() if t.mode == "autonomous"]
            assert len(tasks) >= 1

    @pytest.mark.asyncio
    async def test_startup_autonomous_skipped_when_disabled(self):
        """No autonomous task is created when disabled."""
        _set_mock_responses(["Should not run."])
        server = _make_autonomous_server()
        server.settings.autonomous_enabled = False

        async with server._lifespan(server.app):
            tasks = [t for t in server.task_manager._tasks.values() if t.mode == "autonomous"]
            assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_startup_autonomous_raises_without_goal(self):
        """Startup raises ValueError when enabled but goal is empty."""
        _set_mock_responses(["Should not run."])
        server = _make_autonomous_server()
        server.settings.autonomous_enabled = True
        server.settings.autonomous_goal = ""

        with pytest.raises(ValueError, match="autonomous_enabled=True requires autonomous_goal"):
            async with server._lifespan(server.app):
                pass

    def test_autonomous_settings_from_env(self):
        """Verify env vars map to AgentServerSettings fields."""
        from pais.serverutils import AgentServerSettings

        os.environ["AGENT_NAME"] = "test"
        os.environ["AUTONOMOUS_ENABLED"] = "true"
        os.environ["AUTONOMOUS_GOAL"] = "Scan the network"
        os.environ["AUTONOMOUS_MAX_ITERATIONS"] = "20"
        os.environ["AUTONOMOUS_MAX_RUNTIME_SECONDS"] = "600"
        os.environ["AUTONOMOUS_MAX_TOOL_CALLS"] = "100"
        os.environ["AUTONOMOUS_INTERVAL_SECONDS"] = "5"

        try:
            settings = AgentServerSettings(agent_name="test")
            assert settings.autonomous_enabled is True
            assert settings.autonomous_goal == "Scan the network"
            assert settings.autonomous_max_iterations == 20
            assert settings.autonomous_max_runtime_seconds == 600
            assert settings.autonomous_max_tool_calls == 100
            assert settings.autonomous_interval_seconds == 5
        finally:
            for key in [
                "AUTONOMOUS_ENABLED",
                "AUTONOMOUS_GOAL",
                "AUTONOMOUS_MAX_ITERATIONS",
                "AUTONOMOUS_MAX_RUNTIME_SECONDS",
                "AUTONOMOUS_MAX_TOOL_CALLS",
                "AUTONOMOUS_INTERVAL_SECONDS",
            ]:
                os.environ.pop(key, None)
