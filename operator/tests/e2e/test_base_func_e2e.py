"""End-to-end tests for Kubernetes operator deployment.

Tests the agent server running in Kubernetes via Gateway API:
- Health/Ready endpoints
- Agent card at /.well-known/agent
- Task invocation with memory verification
- Chat completions
"""

import pytest
import httpx

from sh import kubectl

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
async def test_agent_redis_memory(test_namespace: str, shared_modelapi: str):
    """Test agent with Redis-backed distributed memory persists across pod restarts."""
    agent_name = "redis-mem-agent"

    # Deploy Redis in the test namespace
    redis_spec = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "redis", "namespace": test_namespace},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "redis"}},
            "template": {
                "metadata": {"labels": {"app": "redis"}},
                "spec": {
                    "containers": [
                        {
                            "name": "redis",
                            "image": "redis:7-alpine",
                            "ports": [{"containerPort": 6379}],
                        }
                    ]
                },
            },
        },
    }
    redis_svc = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "redis", "namespace": test_namespace},
        "spec": {
            "selector": {"app": "redis"},
            "ports": [{"port": 6379, "targetPort": 6379}],
        },
    }
    create_custom_resource(redis_spec, test_namespace)
    create_custom_resource(redis_svc, test_namespace)
    wait_for_deployment(test_namespace, "redis", timeout=120)

    redis_url = f"redis://redis.{test_namespace}.svc.cluster.local:6379"

    # Create agent with redis memory type
    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name=shared_modelapi,
        mcpserver_names=[],
        agent_name=agent_name,
    )
    agent_spec["spec"]["config"]["memory"] = {
        "enabled": True,
        "type": "redis",
    }
    agent_spec["spec"]["container"]["env"].append(
        {"name": "MEMORY_REDIS_URL", "value": redis_url}
    )
    create_custom_resource(agent_spec, test_namespace)

    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_base = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_base)
    await async_wait_for_healthy(agent_base)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Send a chat message
        response = await client.post(
            f"{agent_base}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [{"role": "user", "content": "Say hello"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["object"] == "chat.completion"
        assert len(result["choices"][0]["message"]["content"]) > 0

        # Verify memory events are stored via Redis
        response = await client.get(f"{agent_base}/memory/events")
        assert response.status_code == 200
        memory = response.json()
        assert memory["total"] >= 2, f"Expected >=2 events, got {memory['total']}: {memory}"
        event_types = [e["event_type"] for e in memory["events"]]
        assert "user_message" in event_types, f"Missing user_message in {event_types}"
        initial_total = memory["total"]

    # Delete the agent pod to test persistence across restarts
    kubectl(
        "delete", "pods",
        "-n", test_namespace,
        "-l", f"kaos.tools/agent={agent_name}",
        "--wait=false",
    )

    # Wait for the pod to be recreated by the deployment
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    wait_for_resource_ready(agent_base)
    await async_wait_for_healthy(agent_base)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Verify memory events survived the pod restart (stored in Redis)
        response = await client.get(f"{agent_base}/memory/events")
        assert response.status_code == 200
        memory = response.json()
        assert memory["total"] >= initial_total, (
            f"Events lost after pod restart: had {initial_total}, now {memory['total']}"
        )
