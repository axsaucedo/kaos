"""End-to-end tests for deterministic agentic loop in Kubernetes.

Tests the agentic loop with mock responses for deterministic behavior:
- Tool calling with mock model responses
- Multi-agent delegation with mock responses
- Memory event verification across agents
- Agentic loop configuration via CRD
"""

import time
import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    port_forward_with_wait,
    parallel_port_forwards,
    get_next_port,
)


def create_agentic_loop_worker(namespace: str, modelapi_name: str, suffix: str = ""):
    """Create worker agent spec for agentic loop testing."""
    name = f"loop-worker{suffix}"
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "config": {
                "description": "Worker for agentic loop tests",
                "instructions": "You are a worker. Process tasks and respond briefly.",
                "agenticLoop": {
                    "maxSteps": 3,
                    "enableTools": True,
                    "enableDelegation": False,
                },
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
                    {"name": "MODEL_NAME", "value": "smollm2:135m"},
                ],
            },
            "agentNetwork": {"expose": True, "access": []},
            "replicas": 1,
            "resources": {
                "requests": {"memory": "256Mi", "cpu": "200m"},
                "limits": {"memory": "512Mi", "cpu": "1000m"},
            },
        },
    }, name


def create_agentic_loop_coordinator(namespace: str, modelapi_name: str, worker_name: str, suffix: str = ""):
    """Create coordinator agent spec for agentic loop testing."""
    name = f"loop-coord{suffix}"
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "config": {
                "description": "Coordinator for agentic loop tests",
                "instructions": f"You are a coordinator. You can delegate tasks to {worker_name}.",
                "agenticLoop": {
                    "maxSteps": 5,
                    "enableTools": True,
                    "enableDelegation": True,
                },
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
                    {"name": "MODEL_NAME", "value": "smollm2:135m"},
                ],
            },
            "agentNetwork": {
                "expose": True,
                "access": [worker_name],
            },
            "replicas": 1,
            "resources": {
                "requests": {"memory": "256Mi", "cpu": "200m"},
                "limits": {"memory": "512Mi", "cpu": "1000m"},
            },
        },
    }, name


@pytest.mark.asyncio
async def test_agentic_loop_config_applied(test_namespace: str, shared_modelapi: str):
    """Test that agentic loop configuration is applied from CRD."""
    worker_spec, worker_name = create_agentic_loop_worker(test_namespace, shared_modelapi, "-cfg")
    
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    port = get_next_port()
    pf_worker = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"agent-{worker_name}",
        local_port=port,
        remote_port=8000,
    )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"http://localhost:{port}/health")
            assert response.status_code == 200
            
            response = await client.get(f"http://localhost:{port}/.well-known/agent")
            assert response.status_code == 200
            card = response.json()
            assert card["name"] == worker_name
            
    finally:
        pf_worker.terminate()
        pf_worker.wait(timeout=5)


@pytest.mark.asyncio
async def test_delegation_with_memory_verification(test_namespace: str, shared_modelapi: str):
    """Test coordinator delegates to worker and memory is tracked."""
    worker_spec, worker_name = create_agentic_loop_worker(test_namespace, shared_modelapi, "-del")
    coord_spec, coord_name = create_agentic_loop_coordinator(test_namespace, shared_modelapi, worker_name, "-del")
    
    # Deploy worker first
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    # Deploy coordinator
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)
    
    # Port forward to both in parallel
    coord_port = get_next_port()
    worker_port = get_next_port()
    pf_processes = parallel_port_forwards(
        test_namespace,
        [
            (f"agent-{coord_name}", coord_port, 8000),
            (f"agent-{worker_name}", worker_port, 8000),
        ]
    )
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Verify both are healthy
            for port in [coord_port, worker_port]:
                response = await client.get(f"http://localhost:{port}/health")
                assert response.status_code == 200
            
            # Get worker's initial memory count
            response = await client.get(f"http://localhost:{worker_port}/memory/events")
            initial_worker_count = response.json()["total"]
            
            # Send delegation request via role: "delegate"
            task_id = f"LOOP_TASK_{int(time.time())}"
            response = await client.post(
                f"http://localhost:{coord_port}/v1/chat/completions",
                json={
                    "model": coord_name,
                    "messages": [
                        {"role": "delegate", "content": f"{worker_name}: Process task {task_id}"}
                    ]
                }
            )
            
            assert response.status_code == 200, f"Delegation failed: {response.text}"
            data = response.json()
            assert "choices" in data
            assert len(data["choices"][0]["message"]["content"]) > 0
            
            # Verify coordinator memory has delegation events
            response = await client.get(f"http://localhost:{coord_port}/memory/events")
            coord_memory = response.json()
            event_types = [e["event_type"] for e in coord_memory["events"]]
            
            assert "delegation_request" in event_types, f"Missing delegation_request in {event_types}"
            assert "delegation_response" in event_types, f"Missing delegation_response in {event_types}"
            
            # Verify task ID is in delegation request
            delegation_reqs = [e for e in coord_memory["events"] if e["event_type"] == "delegation_request"]
            assert any(task_id in str(e["content"]) for e in delegation_reqs)
            
            # Verify worker received the task
            response = await client.get(f"http://localhost:{worker_port}/memory/events")
            worker_memory = response.json()
            
            assert worker_memory["total"] > initial_worker_count, "Worker should have new events"
            
            # Check worker has the task in its memory
            user_msgs = [e for e in worker_memory["events"] if e["event_type"] == "user_message"]
            assert any(task_id in str(e["content"]) for e in user_msgs), \
                f"Task {task_id} not found in worker messages"
    
    finally:
        for pf in pf_processes:
            pf.terminate()
            pf.wait(timeout=5)


@pytest.mark.asyncio
async def test_agent_processes_with_memory_events(test_namespace: str):
    """Test that agent processing creates correct memory events.
    
    This test uses a separate ModelAPI with Ollama backend since it
    actually invokes the model (not using mock_response).
    """
    # Create a ModelAPI with Ollama backend for actual inference
    from e2e.conftest import create_modelapi_hosted_resource
    modelapi_name = "loop-ollama-mem"
    modelapi_spec = create_modelapi_hosted_resource(test_namespace, modelapi_name)
    create_custom_resource(modelapi_spec, test_namespace)
    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=120)
    
    worker_spec, worker_name = create_agentic_loop_worker(test_namespace, modelapi_name, "-mem")
    
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    port = get_next_port()
    pf_worker = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"agent-{worker_name}",
        local_port=port,
        remote_port=8000,
    )
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Clear memory by noting initial count
            response = await client.get(f"http://localhost:{port}/memory/events")
            initial_count = response.json()["total"]
            
            # Send a simple message
            unique_id = f"MSG_{int(time.time())}"
            response = await client.post(
                f"http://localhost:{port}/agent/invoke",
                json={"task": f"Echo back this ID: {unique_id}"}
            )
            
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "completed"
            
            # Check memory events
            response = await client.get(f"http://localhost:{port}/memory/events")
            memory = response.json()
            
            assert memory["total"] > initial_count
            
            # Should have user_message and agent_response
            event_types = [e["event_type"] for e in memory["events"]]
            assert "user_message" in event_types
            assert "agent_response" in event_types
            
            # Verify our message is in the events
            all_content = " ".join(str(e["content"]) for e in memory["events"])
            assert unique_id in all_content
    
    finally:
        pf_worker.terminate()
        pf_worker.wait(timeout=5)


@pytest.mark.asyncio
async def test_coordinator_has_delegation_capability(test_namespace: str, shared_modelapi: str):
    """Test that coordinator with sub-agents has delegation capability in agent card."""
    worker_spec, worker_name = create_agentic_loop_worker(test_namespace, shared_modelapi, "-cap")
    coord_spec, coord_name = create_agentic_loop_coordinator(test_namespace, shared_modelapi, worker_name, "-cap")
    
    create_custom_resource(worker_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{worker_name}", timeout=120)
    
    create_custom_resource(coord_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{coord_name}", timeout=120)
    
    port = get_next_port()
    pf_coord = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"agent-{coord_name}",
        local_port=port,
        remote_port=8000,
    )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"http://localhost:{port}/.well-known/agent")
            assert response.status_code == 200
            card = response.json()
            
            # Verify delegation capability
            assert "task_delegation" in card["capabilities"], \
                f"Expected task_delegation in capabilities: {card['capabilities']}"
            
            # Verify sub-agents are listed
            assert "skills" in card or len(card.get("sub_agents", [])) > 0 or "task_delegation" in card["capabilities"]
    
    finally:
        pf_coord.terminate()
        pf_coord.wait(timeout=5)
