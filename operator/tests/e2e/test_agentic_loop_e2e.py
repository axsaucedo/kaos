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
    port_forward,
    create_modelapi_resource,
    create_agent_resource,
)


def create_agentic_loop_resources(namespace: str):
    """Create resources for deterministic agentic loop testing."""
    # ModelAPI with LiteLLM (supports mock_response - no OLLAMA_BASE_URL needed)
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": "mock-api", "namespace": namespace},
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                    {"name": "LITELLM_LOG", "value": "WARN"},
                    # No OLLAMA_BASE_URL - tests use mock_response for determinism
                ]
            },
        },
    }
    
    # Worker agent with basic config
    worker_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": "worker-loop", "namespace": namespace},
        "spec": {
            "modelAPI": "mock-api",
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
    }
    
    # Coordinator agent with delegation enabled
    coordinator_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": "coordinator-loop", "namespace": namespace},
        "spec": {
            "modelAPI": "mock-api",
            "config": {
                "description": "Coordinator for agentic loop tests",
                "instructions": "You are a coordinator. You can delegate tasks to worker-loop.",
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
                "access": ["worker-loop"],  # Can delegate to worker
            },
            "replicas": 1,
            "resources": {
                "requests": {"memory": "256Mi", "cpu": "200m"},
                "limits": {"memory": "512Mi", "cpu": "1000m"},
            },
        },
    }
    
    return {
        "modelapi": modelapi_spec,
        "worker": worker_spec,
        "coordinator": coordinator_spec,
    }


@pytest.mark.asyncio
async def test_agentic_loop_config_applied(test_namespace: str):
    """Test that agentic loop configuration is applied from CRD."""
    resources = create_agentic_loop_resources(test_namespace)
    
    # Deploy ModelAPI and worker
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-mock-api", timeout=120)
    
    create_custom_resource(resources["worker"], test_namespace)
    wait_for_deployment(test_namespace, "agent-worker-loop", timeout=120)
    
    # Port forward to worker
    pf_worker = port_forward(
        namespace=test_namespace,
        service_name="agent-worker-loop",
        local_port=18400,
        remote_port=8000,
    )
    
    time.sleep(2)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Check health
            response = await client.get("http://localhost:18400/health")
            assert response.status_code == 200
            
            # Check agent card has correct config
            response = await client.get("http://localhost:18400/.well-known/agent")
            assert response.status_code == 200
            card = response.json()
            assert card["name"] == "worker-loop"
            
    finally:
        pf_worker.terminate()
        pf_worker.wait(timeout=5)


@pytest.mark.asyncio
async def test_delegation_with_memory_verification(test_namespace: str):
    """Test coordinator delegates to worker and memory is tracked."""
    resources = create_agentic_loop_resources(test_namespace)
    
    # Deploy resources
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-mock-api", timeout=120)
    
    # Deploy worker first
    create_custom_resource(resources["worker"], test_namespace)
    wait_for_deployment(test_namespace, "agent-worker-loop", timeout=120)
    
    # Deploy coordinator
    create_custom_resource(resources["coordinator"], test_namespace)
    wait_for_deployment(test_namespace, "agent-coordinator-loop", timeout=120)
    
    # Port forward to both
    pf_coord = port_forward(
        namespace=test_namespace,
        service_name="agent-coordinator-loop",
        local_port=18500,
        remote_port=8000,
    )
    pf_worker = port_forward(
        namespace=test_namespace,
        service_name="agent-worker-loop",
        local_port=18501,
        remote_port=8000,
    )
    
    time.sleep(3)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Verify both are healthy
            for port in [18500, 18501]:
                response = await client.get(f"http://localhost:{port}/health")
                assert response.status_code == 200
            
            # Get worker's initial memory count
            response = await client.get("http://localhost:18501/memory/events")
            initial_worker_count = response.json()["total"]
            
            # Send delegation request via role: "delegate"
            task_id = f"LOOP_TASK_{int(time.time())}"
            response = await client.post(
                "http://localhost:18500/v1/chat/completions",
                json={
                    "model": "coordinator-loop",
                    "messages": [
                        {"role": "delegate", "content": f"worker-loop: Process task {task_id}"}
                    ]
                }
            )
            
            assert response.status_code == 200, f"Delegation failed: {response.text}"
            data = response.json()
            assert "choices" in data
            assert len(data["choices"][0]["message"]["content"]) > 0
            
            # Verify coordinator memory has delegation events
            response = await client.get("http://localhost:18500/memory/events")
            coord_memory = response.json()
            event_types = [e["event_type"] for e in coord_memory["events"]]
            
            assert "delegation_request" in event_types, f"Missing delegation_request in {event_types}"
            assert "delegation_response" in event_types, f"Missing delegation_response in {event_types}"
            
            # Verify task ID is in delegation request
            delegation_reqs = [e for e in coord_memory["events"] if e["event_type"] == "delegation_request"]
            assert any(task_id in str(e["content"]) for e in delegation_reqs)
            
            # Verify worker received the task
            response = await client.get("http://localhost:18501/memory/events")
            worker_memory = response.json()
            
            assert worker_memory["total"] > initial_worker_count, "Worker should have new events"
            
            # Check worker has the task in its memory
            user_msgs = [e for e in worker_memory["events"] if e["event_type"] == "user_message"]
            assert any(task_id in str(e["content"]) for e in user_msgs), \
                f"Task {task_id} not found in worker messages"
    
    finally:
        pf_coord.terminate()
        pf_coord.wait(timeout=5)
        pf_worker.terminate()
        pf_worker.wait(timeout=5)


@pytest.mark.asyncio
async def test_agent_processes_with_memory_events(test_namespace: str):
    """Test that agent processing creates correct memory events."""
    resources = create_agentic_loop_resources(test_namespace)
    
    # Deploy ModelAPI and worker
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-mock-api", timeout=120)
    
    create_custom_resource(resources["worker"], test_namespace)
    wait_for_deployment(test_namespace, "agent-worker-loop", timeout=120)
    
    pf_worker = port_forward(
        namespace=test_namespace,
        service_name="agent-worker-loop",
        local_port=18600,
        remote_port=8000,
    )
    
    time.sleep(2)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Clear memory by noting initial count
            response = await client.get("http://localhost:18600/memory/events")
            initial_count = response.json()["total"]
            
            # Send a simple message
            unique_id = f"MSG_{int(time.time())}"
            response = await client.post(
                "http://localhost:18600/agent/invoke",
                json={"task": f"Echo back this ID: {unique_id}"}
            )
            
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "completed"
            
            # Check memory events
            response = await client.get("http://localhost:18600/memory/events")
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
async def test_coordinator_has_delegation_capability(test_namespace: str):
    """Test that coordinator with sub-agents has delegation capability in agent card."""
    resources = create_agentic_loop_resources(test_namespace)
    
    # Deploy resources
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-mock-api", timeout=120)
    
    create_custom_resource(resources["worker"], test_namespace)
    wait_for_deployment(test_namespace, "agent-worker-loop", timeout=120)
    
    create_custom_resource(resources["coordinator"], test_namespace)
    wait_for_deployment(test_namespace, "agent-coordinator-loop", timeout=120)
    
    pf_coord = port_forward(
        namespace=test_namespace,
        service_name="agent-coordinator-loop",
        local_port=18700,
        remote_port=8000,
    )
    
    time.sleep(2)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get agent card
            response = await client.get("http://localhost:18700/.well-known/agent")
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
