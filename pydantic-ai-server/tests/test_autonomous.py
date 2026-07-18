"""Tests for autonomous execution via LocalTaskManager."""

import json
import os
import pytest

from pais.a2a import (
    AutonomousConfig,
    LocalTaskManager,
    TaskState,
    TaskBudgets,
    EVENT_AUTONOMOUS_BUDGET_EXHAUSTED,
    EVENT_TASK_SUBMITTED,
    EVENT_TASK_COMPLETED,
)
import kaos_identity
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
            "Analyze the data", budgets=TaskBudgets(max_iterations=10)
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.output is not None
        assert len(completed.output) > 0
        assert completed.status.state.value == "completed"

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
            budgets=TaskBudgets(max_iterations=2, max_tool_calls=100),
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
            budgets=TaskBudgets(max_iterations=100, max_tool_calls=1, max_runtime_seconds=300),
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
            budgets=TaskBudgets(max_iterations=10),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert "final report" in completed.output.lower() or "complete" in completed.output.lower()
        event_types = [e.type for e in completed.events]
        assert EVENT_TASK_SUBMITTED in event_types
        assert EVENT_TASK_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_state_transition_events_emitted(self):
        """Verify task state transition events during autonomous execution."""
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
            budgets=TaskBudgets(max_iterations=10),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None

        event_types = [e.type for e in completed.events]
        assert EVENT_TASK_SUBMITTED in event_types
        assert EVENT_TASK_COMPLETED in event_types
        assert completed.output is not None
        assert len(completed.output) > 0

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
            budgets=TaskBudgets(max_iterations=0, max_runtime_seconds=0, max_tool_calls=0),
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
            budgets=TaskBudgets(max_iterations=10, interval_seconds=0),
        )
        completed = await server.task_manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert "done" in completed.output.lower()


class TestAutonomousIdentity:
    def test_server_uses_canonical_agent_identity_for_autonomous_principal(self):
        identity = "kaos://agent/memv2-final/autonomous-agent"
        server = make_test_server(
            name="autonomous-agent",
            task_manager_type="local",
            agent_identity=identity,
        )

        assert server.task_manager._autonomous_principal == identity

    @pytest.mark.asyncio
    async def test_self_subjects_with_current_actor_token_each_iteration(self, monkeypatch):
        snapshots = []
        tokens = iter(["agent-token-1", "agent-token-2"])

        async def actor_token_async():
            return next(tokens)

        holder = {}

        async def process_fn(message, session_id):
            snapshots.append((kaos_identity.current(), kaos_identity.to_headers()))
            if len(snapshots) == 2:
                holder["tm"]._transition(task.id, TaskState.CANCELED)
            return "working", 1

        monkeypatch.setattr(kaos_identity, "actor_token_async", actor_token_async)
        tm = LocalTaskManager(process_fn, autonomous_principal="kaos://agent/default/researcher")
        holder["tm"] = tm
        try:
            task = await tm.submit_autonomous(
                "research",
                autonomous_config=AutonomousConfig(max_iter_runtime_seconds=5),
            )
            await tm.wait_for_completion(task.id, timeout=5.0)

            assert [snapshot[0]["subject_token"] for snapshot in snapshots] == [
                "agent-token-1",
                "agent-token-2",
            ]
            for context, headers in snapshots:
                assert context["principal"] == "kaos://agent/default/researcher"
                assert headers["authorization"] == f"Bearer {context['subject_token']}"
                assert headers["x-agent-authorization"] == (f"Bearer {context['subject_token']}")
            assert kaos_identity.current() == {}
        finally:
            await tm.shutdown()

    @pytest.mark.asyncio
    async def test_no_actor_token_runs_without_subject(self, monkeypatch):
        snapshots = []

        async def actor_token_async():
            return None

        holder = {}

        async def process_fn(message, session_id):
            snapshots.append(kaos_identity.current())
            holder["tm"]._transition(task.id, TaskState.CANCELED)
            return "working", 1

        monkeypatch.setattr(kaos_identity, "actor_token_async", actor_token_async)
        tm = LocalTaskManager(process_fn, autonomous_principal="kaos://agent/default/researcher")
        holder["tm"] = tm
        try:
            task = await tm.submit_autonomous(
                "research",
                autonomous_config=AutonomousConfig(max_iter_runtime_seconds=5),
            )
            await tm.wait_for_completion(task.id, timeout=5.0)

            assert snapshots == [{}]
        finally:
            await tm.shutdown()


class TestStartupAutonomous:
    """Tests for startup-activated autonomous mode."""

    def setup_method(self):
        _clear_mock_responses()

    def teardown_method(self):
        _clear_mock_responses()

    @pytest.mark.asyncio
    async def test_startup_autonomous_triggered(self):
        """Autonomous execution is triggered during lifespan when goal is set."""
        _set_mock_responses(["Goal achieved."])
        server = _make_autonomous_server()
        server.settings.autonomous_goal = "Monitor the system"

        async with server._lifespan(server.app):
            tasks = [t for t in server.task_manager._tasks.values() if t.autonomous]
            assert len(tasks) >= 1

    @pytest.mark.asyncio
    async def test_startup_autonomous_skipped_when_no_goal(self):
        """No autonomous task is created when goal is empty."""
        _set_mock_responses(["Should not run."])
        server = _make_autonomous_server()
        server.settings.autonomous_goal = ""

        async with server._lifespan(server.app):
            tasks = [t for t in server.task_manager._tasks.values() if t.autonomous]
            assert len(tasks) == 0

    def test_autonomous_settings_from_env(self):
        """Verify env vars map to AgentServerSettings fields."""
        from pais.serverutils import AgentServerSettings

        os.environ["AGENT_NAME"] = "test"
        os.environ["AUTONOMOUS_GOAL"] = "Scan the network"
        os.environ["AUTONOMOUS_MAX_ITER_RUNTIME_SECONDS"] = "120"
        os.environ["AUTONOMOUS_INTERVAL_SECONDS"] = "5"
        os.environ["TASK_MAX_ITERATIONS"] = "20"
        os.environ["TASK_MAX_RUNTIME_SECONDS"] = "600"
        os.environ["TASK_MAX_TOOL_CALLS"] = "100"

        try:
            settings = AgentServerSettings(agent_name="test")
            assert settings.autonomous_goal == "Scan the network"
            assert settings.autonomous_max_iter_runtime_seconds == 120
            assert settings.autonomous_interval_seconds == 5
            assert settings.task_max_iterations == 20
            assert settings.task_max_runtime_seconds == 600
            assert settings.task_max_tool_calls == 100
        finally:
            for key in [
                "AUTONOMOUS_GOAL",
                "AUTONOMOUS_MAX_ITER_RUNTIME_SECONDS",
                "AUTONOMOUS_INTERVAL_SECONDS",
                "TASK_MAX_ITERATIONS",
                "TASK_MAX_RUNTIME_SECONDS",
                "TASK_MAX_TOOL_CALLS",
            ]:
                os.environ.pop(key, None)


class TestAutonomousAccessOutcome:
    """A gateway access denial during an iteration records a user_action_required event."""

    @pytest.mark.asyncio
    async def test_reauth_outcome_records_event_and_completes(self):
        from kaos_identity import AccessDecision, ReauthenticationRequired
        from pais.a2a import LocalTaskManager, EVENT_USER_ACTION_REQUIRED

        calls = {"n": 0}

        async def process_fn(message, session_id):
            calls["n"] += 1
            decision = AccessDecision(
                allowed=False,
                reason="third_party_reauth_required",
                resource="github",
                reauth_url="https://idp.example/reauth",
            )
            raise ReauthenticationRequired(decision)

        tm = LocalTaskManager(process_fn)
        try:
            task = await tm.submit_autonomous("do it", budgets=TaskBudgets(max_iterations=5))
            completed = await tm.wait_for_completion(task.id, timeout=5.0)
            assert completed is not None
            events = [e for e in completed.events if e.type == EVENT_USER_ACTION_REQUIRED]
            assert len(events) == 1  # exactly one — no retry storm
            assert events[0].data["reason"] == "third_party_reauth_required"
            assert events[0].data["resource"] == "github"
            assert events[0].data["reauth_url"] == "https://idp.example/reauth"
            assert completed.metadata.get("user_action_required") is not None
            assert completed.status.state.value == "completed"
            assert calls["n"] == 1  # stopped after the first denial, did not loop
        finally:
            await tm.shutdown()

    @pytest.mark.asyncio
    async def test_platform_denial_records_event_without_url(self):
        from kaos_identity import AccessDecision, AccessDenied
        from pais.a2a import LocalTaskManager, EVENT_USER_ACTION_REQUIRED

        async def process_fn(message, session_id):
            decision = AccessDecision(
                allowed=False, reason="platform_grant_missing", resource="mcp.payments"
            )
            raise AccessDenied(decision)

        tm = LocalTaskManager(process_fn)
        try:
            task = await tm.submit_autonomous("do it", budgets=TaskBudgets(max_iterations=5))
            completed = await tm.wait_for_completion(task.id, timeout=5.0)
            assert completed is not None
            events = [e for e in completed.events if e.type == EVENT_USER_ACTION_REQUIRED]
            assert len(events) == 1
            assert events[0].data["reason"] == "platform_grant_missing"
            assert "reauth_url" not in events[0].data
            assert completed.status.state.value == "completed"
        finally:
            await tm.shutdown()
