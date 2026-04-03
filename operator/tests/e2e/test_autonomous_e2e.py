"""End-to-end tests for autonomous (self-looping) agent execution.

Tests both startup-activated and A2A-triggered autonomous modes:
- Startup-activated: Agent self-loops on pod boot via CRD config
- A2A-triggered: SendMessage with configuration.mode=autonomous
"""

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


def create_autonomous_agent(
    namespace: str,
    modelapi_name: str,
    agent_name: str,
    mock_responses: list,
    mcp_servers: list = None,
    autonomous_config: dict = None,
):
    """Create an agent spec for autonomous testing."""
    env = [
        {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
        {"name": "DEBUG_MOCK_RESPONSES", "value": json.dumps(mock_responses)},
    ]

    spec = {
        "modelAPI": modelapi_name,
        "model": "ollama/smollm2:135m",
        "config": {
            "description": "Autonomous test agent",
            "instructions": "You are an autonomous test agent. Work toward the given goal.",
            "reasoningLoopMaxSteps": 5,
        },
        "container": {"env": env},
        "agentNetwork": {"access": []},
    }

    if mcp_servers:
        spec["mcpServers"] = mcp_servers

    if autonomous_config:
        spec["config"]["autonomous"] = autonomous_config

    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": namespace},
        "spec": spec,
    }


def create_echo_mcp(namespace: str, mcp_name: str = "auto-echo-mcp"):
    """Create an echo MCP server for autonomous agent tool usage."""
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": mcp_name, "namespace": namespace},
        "spec": {
            "runtime": "python-string",
            "params": 'def echo(message: str) -> str:\n    """Echo back the message."""\n    return f"Echo: {message}"',
            "container": {
                "env": [{"name": "LOG_LEVEL", "value": "DEBUG"}],
            },
        },
    }


@pytest.mark.asyncio
async def test_autonomous_a2a_send_message(
    test_namespace: str, shared_modelapi: str
):
    """Test A2A SendMessage with mode=autonomous triggers background execution and completes."""
    agent_name = "auto-a2a-agent"
    mcp_name = "auto-a2a-mcp"

    # Mock: iteration 1 uses tool, iteration 2 is final text (no tools -> loop ends)
    mock_responses = [
        json.dumps(
            {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "echo",
                        "arguments": {"message": "autonomous iteration 1"},
                    }
                ]
            }
        ),
        "Still working on the goal. Need another iteration.",
        "Goal fully achieved. Final report complete.",
    ]

    mcp_spec = create_echo_mcp(test_namespace, mcp_name)
    create_custom_resource(mcp_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp_name}", timeout=120)

    agent_spec = create_autonomous_agent(
        test_namespace,
        shared_modelapi,
        agent_name,
        mock_responses,
        mcp_servers=[mcp_name],
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Send autonomous request
        send_resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": "Analyze the system and report findings",
                            }
                        ],
                    },
                    "configuration": {
                        "mode": "autonomous",
                        "budgets": {
                            "maxIterations": 5,
                            "maxRuntimeSeconds": 60,
                            "maxToolCalls": 10,
                        },
                    },
                },
            },
        )
        assert send_resp.status_code == 200
        send_data = send_resp.json()
        assert "result" in send_data, f"Expected result, got: {send_data}"

        task = send_data["result"]
        task_id = task["id"]
        assert task_id is not None
        assert task.get("mode") == "autonomous"

        # Poll GetTask until completed (autonomous runs in background)
        import asyncio

        for _ in range(30):
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
            assert "result" in get_data, f"Expected result, got: {get_data}"
            state = get_data["result"]["status"]["state"]
            if state in ("completed", "failed"):
                break
            await asyncio.sleep(2)

        assert state == "completed", f"Task ended in state: {state}"

        # Verify events were recorded
        events = get_data["result"].get("events", [])
        event_types = [e["type"] for e in events]
        assert "task.submitted" in event_types
        assert "task.working" in event_types
        assert "autonomous.iteration.started" in event_types
        assert "task.completed" in event_types

        # Verify at least 2 iterations occurred (tool call then final)
        iteration_starts = [e for e in events if e["type"] == "autonomous.iteration.started"]
        assert len(iteration_starts) >= 2, f"Expected >=2 iterations, got {len(iteration_starts)}"

        # Verify history contains agent response with final output
        history = get_data["result"].get("history", [])
        agent_msgs = [m for m in history if m["role"] == "agent"]
        assert len(agent_msgs) >= 1
        final_text = agent_msgs[-1]["parts"][0]["text"]
        assert "Goal fully achieved" in final_text

        # Verify memory has the session
        session_id = get_data["result"]["sessionId"]
        memory_resp = await client.get(
            f"{agent_url}/memory/events",
            params={"session_id": session_id},
        )
        assert memory_resp.status_code == 200
        memory_events = memory_resp.json()
        assert len(memory_events) >= 2, "Expected memory events from autonomous iterations"


@pytest.mark.asyncio
async def test_autonomous_budget_enforcement(
    test_namespace: str, shared_modelapi: str
):
    """Test autonomous execution respects maxIterations budget."""
    agent_name = "auto-budget-agent"
    mcp_name = "auto-budget-mcp"

    # Mock: every iteration uses tools (never naturally completes)
    # With maxIterations=1, should stop after 1 iteration
    mock_responses = [
        json.dumps(
            {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "echo",
                        "arguments": {"message": "iteration work"},
                    }
                ]
            }
        ),
        "Completed iteration 1, need more work.",
        json.dumps(
            {
                "tool_calls": [
                    {
                        "id": "call_2",
                        "name": "echo",
                        "arguments": {"message": "iteration 2 work"},
                    }
                ]
            }
        ),
        "Completed iteration 2, need more work.",
    ]

    mcp_spec = create_echo_mcp(test_namespace, mcp_name)
    create_custom_resource(mcp_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp_name}", timeout=120)

    agent_spec = create_autonomous_agent(
        test_namespace,
        shared_modelapi,
        agent_name,
        mock_responses,
        mcp_servers=[mcp_name],
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Send with max 1 iteration
        send_resp = await client.post(
            f"{agent_url}/",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "id": 1,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {"type": "text", "text": "Run indefinitely"}
                        ],
                    },
                    "configuration": {
                        "mode": "autonomous",
                        "budgets": {"maxIterations": 1},
                    },
                },
            },
        )
        assert send_resp.status_code == 200
        send_data = send_resp.json()
        assert "result" in send_data, f"Expected result, got: {send_data}"
        task_id = send_data["result"]["id"]

        # Poll until done
        import asyncio

        for _ in range(30):
            get_resp = await client.post(
                f"{agent_url}/",
                json={
                    "jsonrpc": "2.0",
                    "method": "GetTask",
                    "id": 2,
                    "params": {"id": task_id},
                },
            )
            get_data = get_resp.json()
            state = get_data["result"]["status"]["state"]
            if state in ("completed", "failed"):
                break
            await asyncio.sleep(2)

        assert state == "completed"

        # Verify budget exhaustion event with reason
        events = get_data["result"].get("events", [])
        event_types = [e["type"] for e in events]
        assert "autonomous.budget.exhausted" in event_types

        budget_event = next(e for e in events if e["type"] == "autonomous.budget.exhausted")
        assert "max_iterations" in budget_event.get("reason", ""), \
            f"Expected max_iterations reason, got: {budget_event}"

        # Verify only 1 iteration occurred
        iteration_starts = [e for e in events if e["type"] == "autonomous.iteration.started"]
        assert len(iteration_starts) == 1, f"Expected 1 iteration, got {len(iteration_starts)}"


@pytest.mark.asyncio
async def test_autonomous_startup_activated(
    test_namespace: str, shared_modelapi: str
):
    """Test startup-activated autonomous mode via CRD autonomous config."""
    agent_name = "auto-startup-agent"

    # Mock: single text response (no tools -> loop ends after 1 iteration)
    mock_responses = ["System health check complete. All systems nominal."]

    agent_spec = create_autonomous_agent(
        test_namespace,
        shared_modelapi,
        agent_name,
        mock_responses,
        autonomous_config={
            "enabled": True,
            "goal": "Check system health and report status",
            "maxIterations": 3,
            "maxRuntimeSeconds": 30,
        },
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    # The startup autonomous task should have been submitted automatically.
    # Give it time to execute, then verify via the agent's health/memory endpoints.
    import asyncio

    await asyncio.sleep(5)

    # Verify agent is healthy (still running after autonomous task)
    async with httpx.AsyncClient(timeout=60.0) as client:
        health_resp = await client.get(f"{agent_url}/health")
        assert health_resp.status_code == 200

        # Verify memory has the autonomous session with actual content
        memory_resp = await client.get(f"{agent_url}/memory/sessions")
        assert memory_resp.status_code == 200
        sessions = memory_resp.json()
        assert len(sessions) >= 1, "Expected at least one session from startup autonomous run"

        # Verify memory events in the session contain the goal and response
        session_id = sessions[0]
        events_resp = await client.get(
            f"{agent_url}/memory/events",
            params={"session_id": session_id},
        )
        assert events_resp.status_code == 200
        events = events_resp.json()
        assert len(events) >= 2, "Expected at least goal + response events"

        # Verify the agent produced a response matching the mock
        event_contents = [e.get("content", "") for e in events]
        has_response = any("System health check complete" in c for c in event_contents)
        assert has_response, f"Expected mock response in events, got: {event_contents}"
