"""End-to-end tests for deterministic agentic loop in Kubernetes.

Tests the agentic loop via Gateway API:
- Tool calling with DEBUG_MOCK_RESPONSES
- Multi-agent delegation with mock responses
- Memory event verification across agents
- Agentic loop configuration via CRD
"""

import os
import time
import json
import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    wait_for_resource_ready,
    gateway_url,
    create_modelapi_hosted_resource,
)


def create_agentic_loop_worker(
    namespace: str, 
    modelapi_name: str, 
    suffix: str = "", 
    model_name: str = "ollama/smollm2:135m",
    mock_responses: list = None
):
    """Create worker agent spec for agentic loop testing.
    
    Args:
        model_name: Model name. For Proxy mode use 'ollama/smollm2:135m', 
                   for Hosted mode use 'smollm2:135m'.
        mock_responses: List of mock responses for DEBUG_MOCK_RESPONSES env var.
    """
    name = f"loop-worker{suffix}"
    env = [
        {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
        {"name": "MODEL_NAME", "value": model_name},
    ]
    if mock_responses:
        env.append({"name": "DEBUG_MOCK_RESPONSES", "value": json.dumps(mock_responses)})
    
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "config": {
                "description": "Worker for agentic loop tests",
                "instructions": "You are a worker. Process tasks and respond briefly.",
                "reasoningLoopMaxSteps": 3,
                "env": env,
            },
            "agentNetwork": {"access": []},
        },
    }, name


def create_agentic_loop_coordinator(
    namespace: str, 
    modelapi_name: str, 
    worker_name: str, 
    suffix: str = "", 
    model_name: str = "ollama/smollm2:135m",
    mock_responses: list = None
):
    """Create coordinator agent spec for agentic loop testing.
    
    Args:
        model_name: Model name. For Proxy mode use 'ollama/smollm2:135m', 
                   for Hosted mode use 'smollm2:135m'.
        mock_responses: List of mock responses for DEBUG_MOCK_RESPONSES env var.
    """
    name = f"loop-coord{suffix}"
    env = [
        {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
        {"name": "MODEL_NAME", "value": model_name},
    ]
    if mock_responses:
        env.append({"name": "DEBUG_MOCK_RESPONSES", "value": json.dumps(mock_responses)})
    
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "config": {
                "description": "Coordinator for agentic loop tests",
                "instructions": f"You are a coordinator. You can delegate tasks to {worker_name}.",
                "reasoningLoopMaxSteps": 5,
                "env": env,
            },
            "agentNetwork": {"access": [worker_name]},
        },
    }, name


@pytest.mark.asyncio
async def test_agentic_loop_config_applied(test_namespace: str, shared_modelapi: str):
    """Test that agentic loop configuration is applied from CRD."""
    worker_spec, worker_name = create_agentic_loop_worker(test_namespace, shared_modelapi, "-cfg")
    
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    worker_url = gateway_url(test_namespace, "agent", worker_name)
    wait_for_resource_ready(worker_url)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{worker_url}/health")
        assert response.status_code == 200
        
        response = await client.get(f"{worker_url}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == worker_name


@pytest.mark.asyncio
async def test_delegation_with_memory_verification(test_namespace: str, shared_modelapi: str):
    """Test coordinator delegates to worker and memory is tracked.
    
    Uses DEBUG_MOCK_RESPONSES to trigger deterministic delegation.
    """
    task_id = f"LOOP_TASK_{int(time.time())}"
    
    # Create worker with mock response
    worker_spec, worker_name = create_agentic_loop_worker(
        test_namespace, shared_modelapi, "-del",
        mock_responses=[f"Task {task_id} processed successfully by worker."]
    )
    
    # Create coordinator with mock response that triggers delegation
    coord_mock_responses = [
        f'''I'll delegate this to the worker.
```delegate
{{"agent": "{worker_name}", "task": "Process task {task_id}"}}
```''',
        f"The worker has completed task {task_id}."
    ]
    coord_spec, coord_name = create_agentic_loop_coordinator(
        test_namespace, shared_modelapi, worker_name, "-del",
        mock_responses=coord_mock_responses
    )
    
    # Deploy worker first
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    # Deploy coordinator
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)
    
    coord_url = gateway_url(test_namespace, "agent", coord_name)
    worker_url = gateway_url(test_namespace, "agent", worker_name)
    
    wait_for_resource_ready(coord_url)
    wait_for_resource_ready(worker_url)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Verify both are healthy
        for url in [coord_url, worker_url]:
            response = await client.get(f"{url}/health")
            assert response.status_code == 200
        
        # Get worker's initial memory count
        response = await client.get(f"{worker_url}/memory/events")
        initial_worker_count = response.json()["total"]
        
        # Send user message - mock responses will trigger delegation
        response = await client.post(
            f"{coord_url}/v1/chat/completions",
            json={
                "model": coord_name,
                "messages": [
                    {"role": "user", "content": f"Please process task {task_id}"}
                ]
            }
        )
        
        assert response.status_code == 200, f"Request failed: {response.text}"
        data = response.json()
        assert "choices" in data
        assert len(data["choices"][0]["message"]["content"]) > 0
        
        # Verify coordinator memory has delegation events
        response = await client.get(f"{coord_url}/memory/events")
        coord_memory = response.json()
        event_types = [e["event_type"] for e in coord_memory["events"]]
        
        assert "delegation_request" in event_types, f"Missing delegation_request in {event_types}"
        assert "delegation_response" in event_types, f"Missing delegation_response in {event_types}"
        
        # Verify task ID is in delegation request
        delegation_reqs = [e for e in coord_memory["events"] if e["event_type"] == "delegation_request"]
        assert any(task_id in str(e["content"]) for e in delegation_reqs)
        
        # Verify worker received the task
        response = await client.get(f"{worker_url}/memory/events")
        worker_memory = response.json()
        
        assert worker_memory["total"] > initial_worker_count, "Worker should have new events"
        
        # Check worker has task_delegation_received event
        delegation_received = [e for e in worker_memory["events"] if e["event_type"] == "task_delegation_received"]
        assert len(delegation_received) >= 1, f"Worker should have task_delegation_received event"


@pytest.mark.asyncio
async def test_agent_processes_with_memory_events(test_namespace: str, shared_modelapi: str):
    """Test that agent processing creates memory events correctly.
    
    Uses delegation with mock responses for deterministic testing.
    Memory events are verified after delegation completes.
    """
    task_id = f"MEM_{int(time.time())}"
    
    # Create worker with mock response
    worker_spec, worker_name = create_agentic_loop_worker(
        test_namespace, shared_modelapi, "-mem",
        mock_responses=[f"Memory test {task_id} completed."]
    )
    
    # Create coordinator with delegation mock response
    coord_mock_responses = [
        f'''```delegate
{{"agent": "{worker_name}", "task": "Process memory test {task_id}"}}
```''',
        f"Memory test {task_id} has been processed."
    ]
    coord_spec, coord_name = create_agentic_loop_coordinator(
        test_namespace, shared_modelapi, worker_name, "-mem",
        mock_responses=coord_mock_responses
    )
    
    # Deploy worker first
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    # Deploy coordinator
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)
    
    worker_url = gateway_url(test_namespace, "agent", worker_name)
    coord_url = gateway_url(test_namespace, "agent", coord_name)
    wait_for_resource_ready(worker_url)
    wait_for_resource_ready(coord_url)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Note initial worker memory count
        response = await client.get(f"{worker_url}/memory/events")
        initial_count = response.json()["total"]
        
        # Send user message - mock responses trigger delegation
        response = await client.post(
            f"{coord_url}/v1/chat/completions",
            json={
                "model": coord_name,
                "messages": [
                    {"role": "user", "content": f"Process memory test {task_id}"}
                ]
            }
        )
        
        assert response.status_code == 200, f"Request failed: {response.text}"
        
        # Check worker memory events - should have recorded the delegated task
        response = await client.get(f"{worker_url}/memory/events")
        memory = response.json()
        
        assert memory["total"] > initial_count, "Worker should have new memory events"
        
        # Should have task_delegation_received from delegation
        event_types = [e["event_type"] for e in memory["events"]]
        assert "task_delegation_received" in event_types, f"Expected task_delegation_received in {event_types}"
        
        # Verify our unique ID is in the events
        all_content = " ".join(str(e["content"]) for e in memory["events"])
        assert task_id in all_content, f"Expected {task_id} in memory events"


@pytest.mark.asyncio
async def test_coordinator_has_delegation_capability(test_namespace: str, shared_modelapi: str):
    """Test that coordinator with sub-agents has delegation capability in agent card."""
    worker_spec, worker_name = create_agentic_loop_worker(test_namespace, shared_modelapi, "-cap")
    coord_spec, coord_name = create_agentic_loop_coordinator(test_namespace, shared_modelapi, worker_name, "-cap")
    
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)
    
    coord_url = gateway_url(test_namespace, "agent", coord_name)
    wait_for_resource_ready(coord_url)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{coord_url}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        
        # Verify delegation capability
        assert "task_delegation" in card["capabilities"], \
            f"Expected task_delegation in capabilities: {card['capabilities']}"


@pytest.mark.asyncio
async def test_wait_for_dependencies_false(test_namespace: str, shared_modelapi: str):
    """Test that agent can start without waiting for dependencies."""
    agent_name = "loop-nowait"
    agent_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": test_namespace},
        "spec": {
            "modelAPI": shared_modelapi,
            "mcpServers": [],
            "waitForDependencies": False,
            "config": {
                "description": "Agent that doesn't wait for dependencies",
                "instructions": "You are a test agent.",
                "reasoningLoopMaxSteps": 3,
            },
            "agentNetwork": {"access": []},
        },
    }
    
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    
    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{agent_url}/health")
        assert response.status_code == 200
        health = response.json()
        assert health["status"] == "healthy"
        assert health["name"] == agent_name
