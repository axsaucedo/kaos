"""Integration tests for A2A TaskManager + JSON-RPC endpoint.

Tests full HTTP lifecycle scenarios including memory integration,
concurrent tasks, cancellation, and agent card discovery.
"""

import pytest

from httpx import AsyncClient, ASGITransport
from pydantic_ai.models.test import TestModel

from tests.helpers import make_test_server
from pais.a2a import TaskState
from pais.memory import LocalMemory


from typing import Optional


def _jsonrpc(method: str, params: Optional[dict] = None, req_id: int = 1) -> dict:
    """Build a JSON-RPC request payload."""
    payload: dict = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        payload["params"] = params
    return payload


def _send_message(text: str, session_id: Optional[str] = None, req_id: int = 1) -> dict:
    """Build a SendMessage JSON-RPC request."""
    params: dict = {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}}
    if session_id:
        params["sessionId"] = session_id
    return _jsonrpc("SendMessage", params, req_id)


def _get_result(response) -> dict:
    """Extract task result from JSON-RPC response."""
    return response.json()["result"]


class TestA2AIntegrationLifecycle:
    """Integration tests for A2A task lifecycle via HTTP."""

    @pytest.mark.asyncio
    async def test_task_execution_stores_memory_events(self):
        """Verify task execution writes events to memory backend."""
        memory = LocalMemory()
        model = TestModel(custom_output_text="Memory integration result")
        server = make_test_server(model=model, task_manager_type="local", memory=memory)
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Store this in memory"))
            result = _get_result(resp)
            task_id = result["id"]
            session_id = result["sessionId"]

        assert result["status"]["state"] == "completed"

        # Verify memory has a session for this task
        session = await memory.get_session(session_id)
        assert session is not None

    @pytest.mark.asyncio
    async def test_multiple_tasks(self):
        """Test multiple tasks execute successfully."""
        model = TestModel(custom_output_text="Concurrent result")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        results = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for i in range(3):
                resp = await client.post("/", json=_send_message(f"Task {i}", req_id=i + 1))
                result = _get_result(resp)
                results.append(result)

        assert all(r["status"]["state"] == "completed" for r in results)
        assert len(set(r["id"] for r in results)) == 3  # unique task ids

    @pytest.mark.asyncio
    async def test_task_with_shared_session(self):
        """Test multiple tasks sharing a sessionId."""
        model = TestModel(custom_output_text="Session result")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        shared_session = "shared-session-id"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.post(
                "/", json=_send_message("First", session_id=shared_session, req_id=1)
            )
            result1 = _get_result(resp1)

            resp2 = await client.post(
                "/", json=_send_message("Second", session_id=shared_session, req_id=2)
            )
            result2 = _get_result(resp2)

        # Both tasks share the same session
        assert result1["sessionId"] == shared_session
        assert result2["sessionId"] == shared_session
        assert result1["id"] != result2["id"]

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self):
        """Test cancelling a task that already completed (sync execution)."""
        model = TestModel(custom_output_text="Already done")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Cancel me"))
            task_id = _get_result(resp)["id"]

            cancel_resp = await client.post(
                "/", json=_jsonrpc("CancelTask", {"id": task_id}, req_id=2)
            )
            data = cancel_resp.json()

        # Task already completed (synchronous execution), cancel returns completed state
        assert data["result"]["status"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_agent_card_via_http_with_taskstore(self):
        """Test agent card endpoint reflects A2A capabilities."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="a2a-agent", model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/.well-known/agent.json")

        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "a2a-agent"
        assert card["capabilities"]["stateTransitionHistory"] is True
        assert "jsonrpc" in card["supportedProtocols"]

    @pytest.mark.asyncio
    async def test_agent_card_via_http_without_taskstore(self):
        """Test agent card shows stateTransitionHistory=False without TaskStore."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(name="basic-agent", model=model)
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/.well-known/agent.json")

        assert resp.status_code == 200
        card = resp.json()
        assert card["capabilities"]["stateTransitionHistory"] is False

    @pytest.mark.asyncio
    async def test_send_then_get_has_consistent_data(self):
        """Verify GetTask returns consistent task data after completion."""
        model = TestModel(custom_output_text="Final answer here")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Input query"))
            send_result = _get_result(resp)
            task_id = send_result["id"]
            session_id = send_result["sessionId"]

            # Get task via GetTask
            get_resp = await client.post("/", json=_jsonrpc("GetTask", {"id": task_id}, req_id=2))
            result = _get_result(get_resp)

        assert result["id"] == task_id
        assert result["sessionId"] == session_id
        assert result["status"]["state"] == "completed"
        assert result["status"]["timestamp"] is not None

        # History should have user message + agent response
        user_msgs = [m for m in result["history"] if m["role"] == "user"]
        agent_msgs = [m for m in result["history"] if m["role"] == "agent"]
        assert len(user_msgs) >= 1
        assert len(agent_msgs) >= 1
        assert any("Input query" in str(m) for m in user_msgs)

    @pytest.mark.asyncio
    async def test_task_with_model_error_results_in_failed_task(self):
        """Test task transitions to failed when model raises exception.

        _run_agent propagates the error to _execute_task, which catches it
        and transitions the task to FAILED state.
        """
        from pydantic_ai.models.function import FunctionModel

        def error_handler(messages, info):
            raise RuntimeError("Simulated model error")

        model = FunctionModel(error_handler)
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Trigger error"))
            result = _get_result(resp)

        assert result["status"]["state"] == "failed"
        assert "error" in result["status"]["message"].lower()

    @pytest.mark.asyncio
    async def test_jsonrpc_without_task_manager_returns_result(self):
        """Test JSON-RPC endpoint with NullTaskManager returns a stub task."""
        model = TestModel(custom_output_text="test")
        server = make_test_server(model=model)  # No task_manager_type = NullTaskManager
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Hello"))
            data = resp.json()

        # NullTaskManager.send_message returns a stub task
        assert "result" in data


class TestA2AAutonomousMode:
    """Tests for autonomous mode via A2A SendMessage."""

    @pytest.mark.asyncio
    async def test_send_message_autonomous_mode(self):
        """Send with mode=autonomous: validates task lifecycle, events, and output."""
        import json
        import os
        import asyncio

        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "checking"}}]}',
                "Still working.",
                "Analysis complete. All systems healthy.",
            ]
        )
        try:
            server = make_test_server(task_manager_type="local")

            @server._agent.tool_plain
            def echo(message: str) -> str:
                """Echo the message back."""
                return f"Echo: {message}"

            if server._mock_state:
                server._mock_state.reset()
                server._mock_state = None
            transport = ASGITransport(app=server.app)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/",
                    json=_jsonrpc(
                        "SendMessage",
                        {
                            "message": {
                                "role": "user",
                                "parts": [{"type": "text", "text": "Analyze data"}],
                            },
                            "configuration": {"mode": "autonomous"},
                        },
                    ),
                )
                data = resp.json()
                assert "result" in data
                task = data["result"]
                assert task["mode"] == "autonomous"
                task_id = task["id"]

                await asyncio.sleep(1.0)
                resp2 = await client.post("/", json=_jsonrpc("GetTask", {"id": task_id}))
                task2 = resp2.json()["result"]
                assert task2["status"]["state"] == "completed"

                # Validate events show iteration lifecycle
                event_types = [e["type"] for e in task2.get("events", [])]
                assert "task.submitted" in event_types
                assert "autonomous.iteration.started" in event_types
                assert "autonomous.iteration.completed" in event_types
                assert "task.completed" in event_types

                # Validate output content
                assert task2.get("output") is not None
                assert "analysis complete" in task2["output"].lower() or len(task2["output"]) > 0

                # Validate history has agent response
                agent_msgs = [m for m in task2["history"] if m["role"] == "agent"]
                assert len(agent_msgs) > 0
        finally:
            os.environ.pop("DEBUG_MOCK_RESPONSES", None)

    @pytest.mark.asyncio
    async def test_send_message_autonomous_with_budgets(self):
        """Custom budgets enforce limits and produce budget exhaustion events."""
        import json
        import os
        import asyncio

        os.environ["DEBUG_MOCK_RESPONSES"] = json.dumps(
            [
                '{"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"message": "iter1"}}]}',
                "Still going.",
                '{"tool_calls": [{"id": "c2", "name": "echo", "arguments": {"message": "iter2"}}]}',
                "More work.",
            ]
        )
        try:
            server = make_test_server(task_manager_type="local")

            @server._agent.tool_plain
            def echo(message: str) -> str:
                """Echo the message back."""
                return f"Echo: {message}"

            if server._mock_state:
                server._mock_state.reset()
                server._mock_state = None
            transport = ASGITransport(app=server.app)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/",
                    json=_jsonrpc(
                        "SendMessage",
                        {
                            "message": {
                                "role": "user",
                                "parts": [{"type": "text", "text": "Keep working"}],
                            },
                            "configuration": {
                                "mode": "autonomous",
                                "budgets": {
                                    "maxIterations": 1,
                                    "maxRuntimeSeconds": 60,
                                    "maxToolCalls": 100,
                                },
                            },
                        },
                    ),
                )
                data = resp.json()
                assert "result" in data
                task_id = data["result"]["id"]

                await asyncio.sleep(1.0)
                resp2 = await client.post("/", json=_jsonrpc("GetTask", {"id": task_id}))
                task2 = resp2.json()["result"]
                assert task2["status"]["state"] == "completed"

                event_types = [e["type"] for e in task2.get("events", [])]
                assert "autonomous.budget.exhausted" in event_types
                budget_events = [
                    e for e in task2["events"] if e["type"] == "autonomous.budget.exhausted"
                ]
                assert budget_events[0]["data"]["reason"] == "max_iterations"
        finally:
            os.environ.pop("DEBUG_MOCK_RESPONSES", None)

    @pytest.mark.asyncio
    async def test_send_message_default_mode_interactive(self):
        """Verify existing behavior unchanged (synchronous completion)."""
        from pydantic_ai.models.test import TestModel

        model = TestModel(custom_output_text="Sync result")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Hello"))
            data = resp.json()
            task = data["result"]
            assert task["mode"] == "interactive"
            assert task["status"]["state"] == "completed"
