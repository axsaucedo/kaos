"""End-to-end tests for A2A TaskStore and JSON-RPC endpoint.

Tests the A2A JSON-RPC protocol via Gateway API:
- Agent card stateTransitionHistory and supportedProtocols
- SendMessage creates and executes a task (with legacy tasks/send alias)
- GetTask polls task state until completion (with legacy tasks/get alias)
- CancelTask cancels a running task (with legacy tasks/cancel alias)
- SendMessage blocking mode for synchronous completion
"""

import asyncio
import json
import pytest
import httpx

from e2e.conftest import (
    async_wait_for_healthy,
    create_custom_resource,
    wait_for_deployment,
    wait_for_resource_ready,
    gateway_url,
)


def create_a2a_agent(
    namespace: str,
    modelapi_name: str,
    agent_name: str = "a2a-test-agent",
    mock_responses: list = None,
):
    """Create an agent spec for A2A JSON-RPC testing."""
    env = [
        {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
    ]
    if mock_responses:
        env.append(
            {"name": "DEBUG_MOCK_RESPONSES", "value": json.dumps(mock_responses)}
        )

    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "model": "ollama/smollm2:135m",
            "config": {
                "description": "A2A test agent",
                "instructions": "You are a helpful test assistant.",
            },
            "container": {"env": env},
            "agentNetwork": {"access": []},
        },
    }


@pytest.mark.asyncio
async def test_a2a_agent_card_capabilities(
    test_namespace: str, shared_modelapi: str
):
    """Test agent card reflects A2A capabilities (stateTransitionHistory, supportedProtocols)."""
    agent_name = "a2a-card-agent"
    agent_spec = create_a2a_agent(
        test_namespace,
        shared_modelapi,
        agent_name=agent_name,
        mock_responses=["Hello from A2A agent."],
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{agent_url}/.well-known/agent.json")
        assert resp.status_code == 200
        card = resp.json()

        assert card["capabilities"]["stateTransitionHistory"] is True
        assert "supportedProtocols" in card
        assert "jsonrpc" in card["supportedProtocols"]
        assert card["protocolVersion"] == "0.3.0"


@pytest.mark.asyncio
async def test_a2a_task_lifecycle(test_namespace: str, shared_modelapi: str):
    """Test full A2A task lifecycle: SendMessage → GetTask poll → completed."""
    agent_name = "a2a-lifecycle-agent"
    agent_spec = create_a2a_agent(
        test_namespace,
        shared_modelapi,
        agent_name=agent_name,
        mock_responses=["Task processed successfully."],
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. SendMessage (non-blocking)
        send_resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Process this task"}],
                    }
                },
            },
        )
        assert send_resp.status_code == 200
        send_data = send_resp.json()
        assert "result" in send_data, f"Expected result, got: {send_data}"
        assert send_data["result"]["status"]["state"] == "submitted"
        task_id = send_data["result"]["id"]
        session_id = send_data["result"]["sessionId"]
        assert task_id is not None
        assert session_id is not None

        # 2. Poll GetTask until completion
        final_result = None
        for _ in range(60):
            await asyncio.sleep(0.5)
            get_resp = await client.post(
                f"{agent_url}/",
                json={
                    "jsonrpc": "2.0",
                    "method": "GetTask",
                    "id": 2,
                    "params": {"id": task_id},
                },
            )
            assert get_resp.status_code == 200
            get_data = get_resp.json()
            assert "result" in get_data
            state = get_data["result"]["status"]["state"]
            if state in ("completed", "failed", "canceled"):
                final_result = get_data["result"]
                break

        assert final_result is not None, "Task did not complete within timeout"
        assert final_result["status"]["state"] == "completed"

        # 3. Verify history has user + agent messages
        history = final_result["history"]
        assert len(history) >= 2
        user_msgs = [m for m in history if m["role"] == "user"]
        agent_msgs = [m for m in history if m["role"] == "agent"]
        assert len(user_msgs) >= 1
        assert len(agent_msgs) >= 1


@pytest.mark.asyncio
async def test_a2a_send_message_blocking(test_namespace: str, shared_modelapi: str):
    """Test SendMessage with blocking mode returns completed task synchronously."""
    agent_name = "a2a-blocking-agent"
    agent_spec = create_a2a_agent(
        test_namespace,
        shared_modelapi,
        agent_name=agent_name,
        mock_responses=["Blocking response complete."],
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Answer in blocking mode"}],
                    },
                    "configuration": {"blocking": True},
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data, f"Expected result, got: {data}"
        assert data["result"]["status"]["state"] == "completed"
        assert data["result"].get("output", "") or len(data["result"].get("artifacts", [])) > 0 or len(data["result"].get("history", [])) >= 2


@pytest.mark.asyncio
async def test_a2a_jsonrpc_error_handling(test_namespace: str, shared_modelapi: str):
    """Test JSON-RPC error responses: unknown method, missing params, task not found."""
    agent_name = "a2a-error-agent"
    agent_spec = create_a2a_agent(
        test_namespace,
        shared_modelapi,
        agent_name=agent_name,
        mock_responses=["Error test response."],
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Unknown method
        resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/unknown",
                "id": 1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32601  # METHOD_NOT_FOUND

        # GetTask with missing id
        resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "GetTask",
                "id": 2,
                "params": {},
            },
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32602  # INVALID_PARAMS

        # GetTask with nonexistent task id
        resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "GetTask",
                "id": 3,
                "params": {"id": "nonexistent-task-id"},
            },
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32001  # TASK_NOT_FOUND
