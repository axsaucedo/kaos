"""Tests for autonomous execution via LocalTaskManager."""

import json
import os
import time
import pytest

from pais.a2a import (
    AutonomousBudgets,
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


def _make_autonomous_server():
    """Create a test server with an echo tool for autonomous tests."""
    server = make_test_server(task_manager_type="local")

    @server._agent.tool_plain
    def echo(message: str) -> str:
        """Echo the message back."""
        return f"Echo: {message}"

    if server._mock_state:
        server._mock_state.reset()
        server._mock_state = None

    return server


class TestAutonomousLoop:
    """Tests for autonomous execution via TaskManager.submit_autonomous()."""

    def setup_method(self):
        _clear_mock_responses()

    def teardown_method(self):
        _clear_mock_responses()

    @pytest.mark.asyncio
    async def test_single_iteration_no_tools(self):
        """Agent responds with pure text — loop terminates after 1 iteration."""
        _set_mock_responses(["The goal is achieved."])
        server = _make_autonomous_server()

        task = await server.task_manager.submit_autonomous(
            "Analyze the data", budgets=AutonomousBudgets(max_iterations=10)
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.output is not None
        assert len(completed.output) > 0

        started = [e for e in completed.events if e.type == EVENT_AUTONOMOUS_ITERATION_STARTED]
        assert len(started) == 1

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

        task = await server.task_manager.submit_autonomous(
            "Process all data",
            budgets=AutonomousBudgets(max_iterations=2, max_tool_calls=100),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        budget_events = [e for e in completed.events if e.type == EVENT_AUTONOMOUS_BUDGET_EXHAUSTED]
        assert len(budget_events) == 1
        assert budget_events[0].data["reason"] == "max_iterations"

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

        task = await server.task_manager.submit_autonomous(
            "Scan everything",
            budgets=AutonomousBudgets(
                max_iterations=100, max_tool_calls=1, max_runtime_seconds=300
            ),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        budget_events = [e for e in completed.events if e.type == EVENT_AUTONOMOUS_BUDGET_EXHAUSTED]
        assert len(budget_events) == 1
        assert budget_events[0].data["reason"] == "max_tool_calls"

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

        task = await server.task_manager.submit_autonomous(
            "Run all steps",
            budgets=AutonomousBudgets(max_iterations=10),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert "final report" in completed.output.lower() or "complete" in completed.output.lower()

        started = [e for e in completed.events if e.type == EVENT_AUTONOMOUS_ITERATION_STARTED]
        assert len(started) == 3

    @pytest.mark.asyncio
    async def test_events_emitted(self):
        """Verify task events during autonomous execution."""
        _set_mock_responses(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "work"}}]}',
                "Still working.",
                "All done, here is the final report.",
            ]
        )
        server = _make_autonomous_server()

        task = await server.task_manager.submit_autonomous(
            "Complete the task",
            budgets=AutonomousBudgets(max_iterations=10),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None

        event_types = [e.type for e in completed.events]
        assert EVENT_AUTONOMOUS_ITERATION_STARTED in event_types
        assert EVENT_AUTONOMOUS_ITERATION_COMPLETED in event_types

        completed_events = [
            e for e in completed.events if e.type == EVENT_AUTONOMOUS_ITERATION_COMPLETED
        ]
        assert any(e.data.get("tool_call_count", 0) > 0 for e in completed_events)

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

        task = await server.task_manager.submit_autonomous(
            "Complete task",
            budgets=AutonomousBudgets(max_iterations=0, max_runtime_seconds=0, max_tool_calls=0),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert "done" in completed.output.lower() or "achieved" in completed.output.lower()
        budget_events = [e for e in completed.events if e.type == EVENT_AUTONOMOUS_BUDGET_EXHAUSTED]
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

        task = await server.task_manager.submit_autonomous(
            "Do task",
            budgets=AutonomousBudgets(max_iterations=10, interval_seconds=0),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert "done" in completed.output.lower()


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
            import asyncio

            await asyncio.sleep(0.5)
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
