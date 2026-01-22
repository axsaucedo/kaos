"""End-to-end tests for multi-agent system in Kubernetes.

Tests multi-agent deployment and delegation via Gateway API:
- Multiple agents deployed and discoverable
- Coordinator with sub-agents configuration
- Delegation triggered by DEBUG_MOCK_RESPONSES (model decides to delegate)
- Memory verification across agents
"""

import time
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


def create_multi_agent_resources(
    namespace: str, modelapi_name: str, suffix: str = "", mock_responses: dict = None
):
    """Create resources for multi-agent cluster.

    Args:
        namespace: Kubernetes namespace
        modelapi_name: Name of the ModelAPI resource
        suffix: Suffix for resource names
        mock_responses: Dict of agent_name -> mock responses list for DEBUG_MOCK_RESPONSES
    """
    worker1_name = f"multi-w1{suffix}"
    worker2_name = f"multi-w2{suffix}"
    coord_name = f"multi-coord{suffix}"

    mock_responses = mock_responses or {}

    def get_env(agent_name, default_instructions):
        """Get env vars including DEBUG_MOCK_RESPONSES if configured."""
        env = [
            {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
        ]
        if agent_name in mock_responses:
            env.append(
                {
                    "name": "DEBUG_MOCK_RESPONSES",
                    "value": json.dumps(mock_responses[agent_name]),
                }
            )
        return env

    worker_1_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": worker1_name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "model": "gpt-3.5-turbo",  # Required: must match ModelAPI's models
            "config": {
                "description": "Worker agent 1",
                "instructions": f"You are {worker1_name}. Always mention '{worker1_name}' in responses. Be brief.",
                "env": get_env(worker1_name, f"You are {worker1_name}."),
            },
            "agentNetwork": {"access": []},
        },
    }

    worker_2_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": worker2_name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "model": "gpt-3.5-turbo",  # Required: must match ModelAPI's models
            "config": {
                "description": "Worker agent 2",
                "instructions": f"You are {worker2_name}. Always mention '{worker2_name}' in responses. Be brief.",
                "env": get_env(worker2_name, f"You are {worker2_name}."),
            },
            "agentNetwork": {"access": []},
        },
    }

    coordinator_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": coord_name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "model": "gpt-3.5-turbo",  # Required: must match ModelAPI's models
            "config": {
                "description": "Coordinator agent",
                "instructions": f"You are the coordinator. You manage {worker1_name} and {worker2_name}.",
                "env": get_env(coord_name, "You are the coordinator."),
            },
            "agentNetwork": {"access": [worker1_name, worker2_name]},
        },
    }

    return {
        "coordinator": (coordinator_spec, coord_name),
        "worker-1": (worker_1_spec, worker1_name),
        "worker-2": (worker_2_spec, worker2_name),
    }


@pytest.mark.asyncio
async def test_multi_agent_deployment_and_discovery(
    test_namespace: str, shared_modelapi: str
):
    """Test all agents deploy and are discoverable."""
    resources = create_multi_agent_resources(test_namespace, shared_modelapi, "-disc")

    # Create workers first
    for agent_key in ["worker-1", "worker-2"]:
        spec, name = resources[agent_key]
        create_custom_resource(spec, test_namespace)
        wait_for_deployment(test_namespace, f"agent-{name}", timeout=120)

    # Create coordinator last
    coord_spec, coord_name = resources["coordinator"]
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)

    _, w1_name = resources["worker-1"]
    _, w2_name = resources["worker-2"]

    # Wait for all to be accessible via Gateway
    for name in [coord_name, w1_name, w2_name]:
        wait_for_resource_ready(gateway_url(test_namespace, "agent", name))

    # Use async helper with retries to handle transient 503s from gateway
    for name in [coord_name, w1_name, w2_name]:
        await async_wait_for_healthy(gateway_url(test_namespace, "agent", name))

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name in [coord_name, w1_name, w2_name]:
            url = gateway_url(test_namespace, "agent", name)

            # Health
            response = await client.get(f"{url}/health")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"

            # Agent card
            response = await client.get(f"{url}/.well-known/agent")
            assert response.status_code == 200
            card = response.json()
            assert card["name"] == name
            assert "message_processing" in card["capabilities"]

        # Coordinator should have delegation capability
        coord_url = gateway_url(test_namespace, "agent", coord_name)
        response = await client.get(f"{coord_url}/.well-known/agent")
        card = response.json()
        assert "task_delegation" in card["capabilities"]


@pytest.mark.asyncio
async def test_multi_agent_delegation_with_memory(
    test_namespace: str, shared_modelapi: str
):
    """Test coordinator delegates to workers and memory is tracked.

    Uses DEBUG_MOCK_RESPONSES to make the coordinator's model response
    contain a delegation block, which triggers actual delegation.
    """
    task_id = f"K8S_DELEGATE_{int(time.time())}"

    # Create resources with mock responses configured
    # Coordinator: first response triggers delegation, second is final response
    # Worker: just responds with acknowledgment
    resources = create_multi_agent_resources(
        test_namespace,
        shared_modelapi,
        "-mem",
        mock_responses={
            f"multi-coord-mem": [
                f"""I'll delegate this task to the worker.
```delegate
{{"agent": "multi-w1-mem", "task": "Process task {task_id}"}}
```""",
                f"The worker has completed task {task_id}.",
            ],
            "multi-w1-mem": [f"Task {task_id} processed by worker-1."],
        },
    )

    # Deploy workers first
    for agent_key in ["worker-1", "worker-2"]:
        spec, name = resources[agent_key]
        create_custom_resource(spec, test_namespace)
        wait_for_deployment(test_namespace, f"agent-{name}", timeout=120)

    # Deploy coordinator
    coord_spec, coord_name = resources["coordinator"]
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)

    _, w1_name = resources["worker-1"]

    coord_url = gateway_url(test_namespace, "agent", coord_name)
    w1_url = gateway_url(test_namespace, "agent", w1_name)

    wait_for_resource_ready(coord_url)
    wait_for_resource_ready(w1_url)

    # Use async helper with retries to handle transient 503s from gateway
    await async_wait_for_healthy(coord_url)
    await async_wait_for_healthy(w1_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get worker-1's initial memory count
        response = await client.get(f"{w1_url}/memory/events")
        initial_count = response.json()["total"]

        # Send user message - mock responses will trigger delegation
        response = await client.post(
            f"{coord_url}/v1/chat/completions",
            json={
                "model": coord_name,
                "messages": [
                    {"role": "user", "content": f"Please process task {task_id}"}
                ],
            },
        )

        assert response.status_code == 200, f"Request failed: {response.text}"
        data = response.json()
        assert "choices" in data
        assert len(data["choices"][0]["message"]["content"]) > 0

        # Verify coordinator memory has delegation events
        response = await client.get(f"{coord_url}/memory/events")
        coord_memory = response.json()

        delegation_reqs = [
            e for e in coord_memory["events"] if e["event_type"] == "delegation_request"
        ]
        delegation_resps = [
            e
            for e in coord_memory["events"]
            if e["event_type"] == "delegation_response"
        ]

        assert (
            len(delegation_reqs) >= 1
        ), f"No delegation_request events found. Events: {[e['event_type'] for e in coord_memory['events']]}"
        assert len(delegation_resps) >= 1, f"No delegation_response events found"
        assert any(task_id in str(e["content"]) for e in delegation_reqs)

        # Verify worker-1 received the task
        response = await client.get(f"{w1_url}/memory/events")
        worker_memory = response.json()

        assert worker_memory["total"] > initial_count

        # Check for task_delegation_received event (new event type for delegated tasks)
        delegation_received = [
            e
            for e in worker_memory["events"]
            if e["event_type"] == "task_delegation_received"
        ]
        assert (
            len(delegation_received) >= 1
        ), f"Worker should have task_delegation_received event"


@pytest.mark.asyncio
async def test_multi_agent_process_independently(
    test_namespace: str, shared_modelapi: str
):
    """Test each agent processes tasks independently with memory isolation."""
    resources = create_multi_agent_resources(test_namespace, shared_modelapi, "-iso")

    # Deploy workers
    for agent_key in ["worker-1", "worker-2"]:
        spec, name = resources[agent_key]
        create_custom_resource(spec, test_namespace)
        wait_for_deployment(test_namespace, f"agent-{name}", timeout=120)

    _, w1_name = resources["worker-1"]
    _, w2_name = resources["worker-2"]

    w1_url = gateway_url(test_namespace, "agent", w1_name)
    w2_url = gateway_url(test_namespace, "agent", w2_name)

    wait_for_resource_ready(w1_url)
    wait_for_resource_ready(w2_url)

    # Use async helper with retries to handle transient 503s from gateway
    await async_wait_for_healthy(w1_url)
    await async_wait_for_healthy(w2_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Send unique tasks
        task1_id = f"W1_TASK_{int(time.time())}"
        task2_id = f"W2_TASK_{int(time.time())}"

        # Chat completions for worker-1
        response = await client.post(
            f"{w1_url}/v1/chat/completions",
            json={
                "model": "worker-1",
                "messages": [{"role": "user", "content": f"Process task {task1_id}"}],
                "stream": False,
            },
        )
        assert response.status_code == 200

        # Chat completions for worker-2
        response = await client.post(
            f"{w2_url}/v1/chat/completions",
            json={
                "model": "worker-2",
                "messages": [{"role": "user", "content": f"Process task {task2_id}"}],
                "stream": False,
            },
        )
        assert response.status_code == 200

        # Verify memory isolation
        response = await client.get(f"{w1_url}/memory/events")
        w1_memory = response.json()
        w1_content = " ".join(str(e["content"]) for e in w1_memory["events"])

        response = await client.get(f"{w2_url}/memory/events")
        w2_memory = response.json()
        w2_content = " ".join(str(e["content"]) for e in w2_memory["events"])

        # Each worker should have its own task, not the other's
        assert task1_id in w1_content
        assert task2_id not in w1_content
        assert task2_id in w2_content
        assert task1_id not in w2_content
