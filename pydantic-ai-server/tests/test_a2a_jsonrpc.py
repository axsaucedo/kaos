"""Tests for A2A JSON-RPC endpoint (POST /).

Tests the JSON-RPC 2.0 dispatcher with tasks/send, tasks/get, tasks/cancel.
"""

import asyncio
import pytest

from httpx import AsyncClient, ASGITransport
from pydantic_ai.models.test import TestModel

from tests.helpers import make_test_server
from pais.taskstore import LocalTaskStore, TaskState


def _make_server_with_taskstore(**kwargs):
    """Create a test server with a LocalTaskStore."""
    task_store = LocalTaskStore()
    model = kwargs.pop("model", TestModel(custom_output_text="Task completed successfully"))
    server = make_test_server(model=model, task_store=task_store, **kwargs)
    return server


class TestJsonRpcEndpoint:
    """Tests for JSON-RPC POST / route."""

    @pytest.mark.asyncio
    async def test_tasks_send_basic(self):
        """Test tasks/send creates a task and returns submitted state."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Hello agent"}],
                        }
                    },
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        result = data["result"]
        assert "id" in result
        assert result["status"]["state"] == "submitted"
        assert len(result["history"]) == 1
        assert result["history"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_tasks_send_with_session_id(self):
        """Test tasks/send with explicit sessionId."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": 1,
                    "params": {
                        "sessionId": "my-session",
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Hello"}],
                        },
                    },
                },
            )

        data = response.json()
        assert data["result"]["sessionId"] == "my-session"

    @pytest.mark.asyncio
    async def test_tasks_send_missing_message(self):
        """Test tasks/send returns error when message is missing."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": 1,
                    "params": {},
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_tasks_send_empty_text(self):
        """Test tasks/send returns error when message has no text."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": 1,
                    "params": {"message": {"role": "user", "parts": []}},
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tasks_get_after_completion(self):
        """Test tasks/get returns completed task with output."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send task
            send_resp = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Hello"}],
                        }
                    },
                },
            )
            task_id = send_resp.json()["result"]["id"]

            # Wait for async execution to complete
            for _ in range(50):
                await asyncio.sleep(0.1)
                get_resp = await client.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "method": "tasks/get",
                        "id": 2,
                        "params": {"id": task_id},
                    },
                )
                data = get_resp.json()
                if data["result"]["status"]["state"] in ("completed", "failed"):
                    break

        assert data["result"]["status"]["state"] == "completed"
        assert len(data["result"]["history"]) >= 2
        agent_msgs = [m for m in data["result"]["history"] if m["role"] == "agent"]
        assert len(agent_msgs) >= 1

    @pytest.mark.asyncio
    async def test_tasks_get_not_found(self):
        """Test tasks/get returns error for unknown task."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "id": 1,
                    "params": {"id": "nonexistent-task"},
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32001  # TASK_NOT_FOUND

    @pytest.mark.asyncio
    async def test_tasks_get_missing_id(self):
        """Test tasks/get returns error when id is missing."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "id": 1,
                    "params": {},
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tasks_cancel_not_found(self):
        """Test tasks/cancel returns error for unknown task."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/cancel",
                    "id": 1,
                    "params": {"id": "nonexistent"},
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tasks_cancel_missing_id(self):
        """Test tasks/cancel returns error when id is missing."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/cancel",
                    "id": 1,
                    "params": {},
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        """Test unknown method returns method not found error."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/unknown",
                    "id": 1,
                },
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32601  # METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        """Test invalid JSON returns parse error."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                content="not json",
                headers={"content-type": "application/json"},
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32700  # PARSE_ERROR

    @pytest.mark.asyncio
    async def test_invalid_jsonrpc_structure(self):
        """Test invalid JSON-RPC structure returns error."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={"not": "jsonrpc"},
            )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32600  # INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_full_lifecycle_send_poll_complete(self):
        """Test complete task lifecycle: send → poll → completed."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Send task
            send_resp = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": "req-1",
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Process this task"}],
                        }
                    },
                },
            )
            assert send_resp.status_code == 200
            task_id = send_resp.json()["result"]["id"]
            session_id = send_resp.json()["result"]["sessionId"]
            assert task_id is not None
            assert session_id is not None

            # 2. Poll until completed
            final_state = None
            for _ in range(50):
                await asyncio.sleep(0.1)
                get_resp = await client.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "method": "tasks/get",
                        "id": "req-2",
                        "params": {"id": task_id},
                    },
                )
                result = get_resp.json()["result"]
                final_state = result["status"]["state"]
                if final_state in ("completed", "failed"):
                    break

            assert final_state == "completed"

            # 3. Verify history has user + agent messages
            history = result["history"]
            assert any(m["role"] == "user" for m in history)
            assert any(m["role"] == "agent" for m in history)


class TestA2ASpecCompliantMethods:
    """Tests for A2A RC v1.0 PascalCase method names and features."""

    @pytest.mark.asyncio
    async def test_send_message_basic(self):
        """Test SendMessage creates a task."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Hello via SendMessage"}],
                        }
                    },
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert data["result"]["status"]["state"] == "submitted"

    @pytest.mark.asyncio
    async def test_get_task_method(self):
        """Test GetTask retrieves a task."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            send_resp = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Test"}],
                        }
                    },
                },
            )
            task_id = send_resp.json()["result"]["id"]

            get_resp = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "GetTask",
                    "id": 2,
                    "params": {"id": task_id},
                },
            )

        data = get_resp.json()
        assert "result" in data
        assert data["result"]["id"] == task_id

    @pytest.mark.asyncio
    async def test_cancel_task_method(self):
        """Test CancelTask cancels a task."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            send_resp = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Cancel me"}],
                        }
                    },
                },
            )
            task_id = send_resp.json()["result"]["id"]

            cancel_resp = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "CancelTask",
                    "id": 2,
                    "params": {"id": task_id},
                },
            )

        data = cancel_resp.json()
        assert data["result"]["status"]["state"] in ("canceled", "completed")

    @pytest.mark.asyncio
    async def test_send_message_blocking(self):
        """Test SendMessage with blocking=true waits for completion."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Blocking request"}],
                        },
                        "configuration": {"blocking": True},
                    },
                },
            )

        assert response.status_code == 200
        data = response.json()
        result = data["result"]
        assert result["status"]["state"] == "completed"
        agent_msgs = [m for m in result["history"] if m["role"] == "agent"]
        assert len(agent_msgs) >= 1

    @pytest.mark.asyncio
    async def test_send_message_with_context_id(self):
        """Test SendMessage with contextId maps to session_id."""
        server = _make_server_with_taskstore()
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "With context"}],
                        },
                        "contextId": "my-context-123",
                    },
                },
            )

        data = response.json()
        assert data["result"]["sessionId"] == "my-context-123"


class TestTaskManagerObservability:
    """Tests for TaskManager OTel instrumentation."""

    @pytest.mark.asyncio
    async def test_task_manager_creates_spans(self):
        """Verify TaskManager methods create OTel spans (no-op when not initialized)."""
        from pais.a2a import TaskManager

        task_store = LocalTaskStore()

        async def mock_process(msg, session_id="", stream=False):
            yield "result"

        manager = TaskManager(task_store, mock_process)
        task = await manager.submit_task("test message")
        assert task.status.state == TaskState.SUBMITTED

        completed = await manager.wait_for_completion(task.id, timeout=5.0)
        assert completed is not None
        assert completed.status.state == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_get_task_metrics_returns_none_when_disabled(self):
        """Verify get_task_metrics returns (None, None) when OTel not initialized."""
        from pais.a2a import get_task_metrics

        counter, histogram = get_task_metrics()
        assert counter is None
        assert histogram is None
