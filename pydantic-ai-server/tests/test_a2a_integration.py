"""Integration tests for A2A TaskStore + JSON-RPC endpoint.

Tests full HTTP lifecycle scenarios including memory integration,
concurrent tasks, cancellation, and agent card discovery.
"""

import asyncio
import pytest

from httpx import AsyncClient, ASGITransport
from pydantic_ai.models.test import TestModel

from tests.helpers import make_test_server
from pais.a2a import TaskState
from pais.memory import LocalMemory


from typing import Optional


def _jsonrpc(method: str, params: Optional[dict] = None, req_id: int = 1) -> dict:
    """Build a JSON-RPC request payload."""
    payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        payload["params"] = params
    return payload


def _send_message(text: str, session_id: Optional[str] = None, req_id: int = 1) -> dict:
    """Build a tasks/send JSON-RPC request."""
    params = {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}}
    if session_id:
        params["sessionId"] = session_id
    return _jsonrpc("tasks/send", params, req_id)


async def _poll_until_done(client: AsyncClient, task_id: str, timeout: float = 5.0):
    """Poll tasks/get until task reaches a terminal state."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.post("/", json=_jsonrpc("tasks/get", {"id": task_id}))
        result = resp.json()["result"]
        state = result["status"]["state"]
        if state in ("completed", "failed", "canceled"):
            return result
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


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
            task_id = resp.json()["result"]["id"]
            session_id = resp.json()["result"]["sessionId"]
            result = await _poll_until_done(client, task_id)

        assert result["status"]["state"] == "completed"

        # Verify memory has a session for this task
        session = await memory.get_session(session_id)
        assert session is not None

    @pytest.mark.asyncio
    async def test_multiple_concurrent_tasks(self):
        """Test multiple tasks can execute concurrently."""
        model = TestModel(custom_output_text="Concurrent result")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        task_ids = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send 3 tasks concurrently
            for i in range(3):
                resp = await client.post("/", json=_send_message(f"Task {i}", req_id=i + 1))
                data = resp.json()
                assert "result" in data
                task_ids.append(data["result"]["id"])

            # Poll all until done
            results = []
            for tid in task_ids:
                result = await _poll_until_done(client, tid)
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
            tid1 = resp1.json()["result"]["id"]
            await _poll_until_done(client, tid1)

            resp2 = await client.post(
                "/", json=_send_message("Second", session_id=shared_session, req_id=2)
            )
            tid2 = resp2.json()["result"]["id"]
            result2 = await _poll_until_done(client, tid2)

        # Both tasks share the same session
        assert resp1.json()["result"]["sessionId"] == shared_session
        assert result2["sessionId"] == shared_session
        assert tid1 != tid2

    @pytest.mark.asyncio
    async def test_cancel_submitted_task(self):
        """Test cancelling a task that was submitted."""
        model = TestModel(custom_output_text="Should not complete")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Cancel me"))
            task_id = resp.json()["result"]["id"]

            cancel_resp = await client.post(
                "/", json=_jsonrpc("tasks/cancel", {"id": task_id}, req_id=2)
            )
            data = cancel_resp.json()

        # Task may have already completed (TestModel is fast) or be canceled
        assert data["result"]["status"]["state"] in ("canceled", "completed")

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
    async def test_tasks_send_then_get_has_consistent_data(self):
        """Verify tasks/get returns consistent task data after completion."""
        model = TestModel(custom_output_text="Final answer here")
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Input query"))
            send_result = resp.json()["result"]
            task_id = send_result["id"]
            session_id = send_result["sessionId"]

            result = await _poll_until_done(client, task_id)

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
    async def test_task_with_model_error_completes_with_error_output(self):
        """Test task completes with error message when model raises exception.

        _process_message catches errors and yields an error string,
        so the task still transitions to completed (not failed).
        """
        from pydantic_ai.models.function import FunctionModel

        def error_handler(messages, info):
            raise RuntimeError("Simulated model error")

        model = FunctionModel(error_handler)
        server = make_test_server(model=model, task_manager_type="local")
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/", json=_send_message("Trigger error"))
            task_id = resp.json()["result"]["id"]
            result = await _poll_until_done(client, task_id, timeout=10.0)

        # _process_message catches the error and yields it as text
        assert result["status"]["state"] == "completed"
        agent_msgs = [m for m in result["history"] if m["role"] == "agent"]
        assert any("error" in str(m).lower() for m in agent_msgs)

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
