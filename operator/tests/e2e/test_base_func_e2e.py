"""End-to-end tests for Kubernetes operator deployment.

Tests the agent server running in Kubernetes via Gateway API:
- Health/Ready endpoints
- Agent card at /.well-known/agent
- Task invocation with memory verification
- Chat completions
"""

import pytest
import httpx
import json
import time

from e2e.conftest import (
    async_wait_for_healthy,
    create_custom_resource,
    wait_for_deployment,
    wait_for_resource_ready,
    gateway_url,
    create_modelapi_hosted_resource,
    create_agent_resource,
)


@pytest.mark.asyncio
async def test_agent_health_discovery_and_invocation(test_namespace: str):
    """Test complete agent workflow: health, discovery, invocation with in-cluster Ollama.

    Uses Hosted mode ModelAPI which runs Ollama in-cluster with smollm2:135m model.
    """
    modelapi_name = "base-ollama-hosted"
    agent_name = "base-test-agent"

    # Use Hosted mode - runs Ollama in-cluster
    modelapi_spec = create_modelapi_hosted_resource(test_namespace, modelapi_name)
    create_custom_resource(modelapi_spec, test_namespace)

    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name=modelapi_name,
        mcpserver_names=[],
        agent_name=agent_name,
        model_name="smollm2:135m",  # Direct Ollama format for Hosted mode
    )
    create_custom_resource(agent_spec, test_namespace)

    # Hosted mode needs longer timeout for model pull
    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=180)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_base = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_base)

    # Use async helper with retries to handle transient 503s from gateway
    await async_wait_for_healthy(agent_base)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Health endpoint
        response = await client.get(f"{agent_base}/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

        # 2. Ready endpoint
        response = await client.get(f"{agent_base}/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

        # 3. Agent card
        response = await client.get(f"{agent_base}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        assert "name" in card
        assert "capabilities" in card
        assert "message_processing" in card["capabilities"]

        # 4. Chat completions (OpenAI-compatible)
        response = await client.post(
            f"{agent_base}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [{"role": "user", "content": "Say hello briefly"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["object"] == "chat.completion"
        assert len(result["choices"]) > 0
        assert len(result["choices"][0]["message"]["content"]) > 0

        # 5. Verify memory events
        response = await client.get(f"{agent_base}/memory/events")
        assert response.status_code == 200
        memory = response.json()
        assert memory["total"] >= 2

        event_types = [e["event_type"] for e in memory["events"]]
        assert "user_message" in event_types
        assert "agent_response" in event_types


@pytest.mark.asyncio
async def test_agent_chat_completions(test_namespace: str, shared_modelapi: str):
    """Test OpenAI-compatible chat completions endpoint."""
    agent_name = "base-chat-agent"

    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name=shared_modelapi,
        mcpserver_names=[],
        agent_name=agent_name,
    )
    create_custom_resource(agent_spec, test_namespace)

    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_base = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_base)

    # Use async helper with retries to handle transient 503s from gateway
    await async_wait_for_healthy(agent_base)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{agent_base}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [{"role": "user", "content": "Say OK"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Verify OpenAI format
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["choices"][0]["message"]["content"]) > 0


@pytest.mark.asyncio
async def test_custom_agent_image(test_namespace: str, shared_modelapi: str):
    """Test Agent with custom container image override.

    Deploys a custom agent image (custom-agent:test) with custom tools (add, multiply,
    random_number) defined in the image. Uses container.image CRD field to override
    the default agent image.
    """
    task_id = f"CUSTOM_{int(time.time())}"
    agent_name = "custom-img-agent"

    # Mock: call custom "add" tool, then return final response
    mock_responses = [
        json.dumps(
            {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "add",
                        "arguments": {"a": 5, "b": 3},
                    }
                ]
            }
        ),
        f"The result of 5 + 3 = 8. Task {task_id} complete.",
    ]

    agent_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": test_namespace},
        "spec": {
            "modelAPI": shared_modelapi,
            "model": "ollama/smollm2:135m",
            "config": {
                "description": "Custom image agent with math tools",
                "instructions": "You are a math agent with add, multiply, and random tools.",
                "reasoningLoopMaxSteps": 5,
            },
            "container": {
                "image": "custom-agent:test",
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
                    {
                        "name": "DEBUG_MOCK_RESPONSES",
                        "value": json.dumps(mock_responses),
                    },
                ],
            },
            "agentNetwork": {"access": []},
        },
    }
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Verify health
        response = await client.get(f"{agent_url}/health")
        assert response.status_code == 200

        # Verify agent card shows custom tools
        response = await client.get(f"{agent_url}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        skill_names = [s.get("name") for s in card.get("skills", [])]
        assert "add" in skill_names, f"add not in skills: {skill_names}"
        assert "multiply" in skill_names, f"multiply not in skills: {skill_names}"
        assert "random_number" in skill_names, f"random_number not in skills: {skill_names}"

        # Send message — mock will trigger add tool call then final response
        response = await client.post(
            f"{agent_url}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [
                    {"role": "user", "content": f"Add 5 and 3 for task {task_id}"}
                ],
            },
        )
        assert response.status_code == 200, f"Request failed: {response.text}"
        data = response.json()
        assert "choices" in data
        assert len(data["choices"][0]["message"]["content"]) > 0

        # Verify memory has tool-related events
        response = await client.get(f"{agent_url}/memory/events")
        memory = response.json()
        event_types = [e["event_type"] for e in memory["events"]]
        assert "tool_call" in event_types, f"Missing tool_call in {event_types}"
        assert "tool_result" in event_types, f"Missing tool_result in {event_types}"

