"""End-to-end tests for multi-agent system in Kubernetes.

Tests multi-agent deployment and delegation:
- Multiple agents deployed and discoverable
- Coordinator with sub-agents configuration
- Delegation via chat completions with role: "delegate"
- Memory verification across agents
"""

import time
import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    port_forward,
    create_modelapi_resource,
)


def create_multi_agent_resources(namespace: str):
    """Create resources for multi-agent cluster."""
    # ModelAPI with LiteLLM (supports mock_response - no OLLAMA_BASE_URL needed)
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": "multi-agent-api", "namespace": namespace},
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
    
    worker_1_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": "worker-1", "namespace": namespace},
        "spec": {
            "modelAPI": "multi-agent-api",
            "config": {
                "description": "Worker agent 1",
                "instructions": "You are worker-1. Always mention 'worker-1' in responses. Be brief.",
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
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
    
    worker_2_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": "worker-2", "namespace": namespace},
        "spec": {
            "modelAPI": "multi-agent-api",
            "config": {
                "description": "Worker agent 2",
                "instructions": "You are worker-2. Always mention 'worker-2' in responses. Be brief.",
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
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
    
    coordinator_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": "coordinator", "namespace": namespace},
        "spec": {
            "modelAPI": "multi-agent-api",
            "config": {
                "description": "Coordinator agent",
                "instructions": "You are the coordinator. You manage worker-1 and worker-2.",
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
                    {"name": "MODEL_NAME", "value": "smollm2:135m"},
                ],
            },
            "agentNetwork": {
                "expose": True,
                "access": ["worker-1", "worker-2"],  # This configures sub-agents
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
        "coordinator": coordinator_spec,
        "worker-1": worker_1_spec,
        "worker-2": worker_2_spec,
    }


@pytest.mark.asyncio
async def test_multi_agent_deployment_and_discovery(test_namespace: str):
    """Test all agents deploy and are discoverable."""
    resources = create_multi_agent_resources(test_namespace)
    
    # Create ModelAPI first
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-multi-agent-api", timeout=120)
    
    # Create workers first (so coordinator can discover them)
    for agent_name in ["worker-1", "worker-2"]:
        create_custom_resource(resources[agent_name], test_namespace)
        wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    
    # Create coordinator last
    create_custom_resource(resources["coordinator"], test_namespace)
    wait_for_deployment(test_namespace, "agent-coordinator", timeout=120)
    
    # Test discovery for each agent
    agent_ports = {"coordinator": 18100, "worker-1": 18101, "worker-2": 18102}
    pf_processes = []
    
    for agent_name, port in agent_ports.items():
        pf = port_forward(
            namespace=test_namespace,
            service_name=f"agent-{agent_name}",
            local_port=port,
            remote_port=8000,
        )
        pf_processes.append(pf)
    
    time.sleep(2)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for agent_name, port in agent_ports.items():
                # Health
                response = await client.get(f"http://localhost:{port}/health")
                assert response.status_code == 200
                assert response.json()["status"] == "healthy"
                
                # Agent card
                response = await client.get(f"http://localhost:{port}/.well-known/agent")
                assert response.status_code == 200
                card = response.json()
                assert card["name"] == agent_name
                assert "message_processing" in card["capabilities"]
            
            # Coordinator should have delegation capability
            response = await client.get(f"http://localhost:18100/.well-known/agent")
            card = response.json()
            assert "task_delegation" in card["capabilities"]
    
    finally:
        for pf in pf_processes:
            pf.terminate()
            pf.wait(timeout=5)


@pytest.mark.asyncio
async def test_multi_agent_delegation_with_memory(test_namespace: str):
    """Test coordinator delegates to workers and memory is tracked."""
    resources = create_multi_agent_resources(test_namespace)
    
    # Deploy resources
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-multi-agent-api", timeout=120)
    
    for agent_name in ["worker-1", "worker-2"]:
        create_custom_resource(resources[agent_name], test_namespace)
        wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    
    create_custom_resource(resources["coordinator"], test_namespace)
    wait_for_deployment(test_namespace, "agent-coordinator", timeout=120)
    
    # Port forward to coordinator and worker-1
    pf_coordinator = port_forward(
        namespace=test_namespace,
        service_name="agent-coordinator",
        local_port=18200,
        remote_port=8000,
    )
    pf_worker1 = port_forward(
        namespace=test_namespace,
        service_name="agent-worker-1",
        local_port=18201,
        remote_port=8000,
    )
    
    time.sleep(2)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Get worker-1's initial memory count
            response = await client.get("http://localhost:18201/memory/events")
            initial_count = response.json()["total"]
            
            # Delegate via chat completions
            task_id = f"K8S_DELEGATE_{int(time.time())}"
            response = await client.post(
                "http://localhost:18200/v1/chat/completions",
                json={
                    "model": "coordinator",
                    "messages": [
                        {"role": "delegate", "content": f"worker-1: Process task {task_id}"}
                    ]
                }
            )
            
            if response.status_code != 200:
                print(f"DEBUG: Delegation failed with status {response.status_code}")
                print(f"DEBUG: Response body: {response.text}")
            
            assert response.status_code == 200, f"Delegation failed: {response.text}"
            data = response.json()
            assert "choices" in data
            assert len(data["choices"][0]["message"]["content"]) > 0
            
            # Verify coordinator memory has delegation events
            response = await client.get("http://localhost:18200/memory/events")
            coord_memory = response.json()
            
            delegation_reqs = [e for e in coord_memory["events"] if e["event_type"] == "delegation_request"]
            delegation_resps = [e for e in coord_memory["events"] if e["event_type"] == "delegation_response"]
            
            assert len(delegation_reqs) >= 1
            assert len(delegation_resps) >= 1
            assert any(task_id in str(e["content"]) for e in delegation_reqs)
            
            # Verify worker-1 received the task
            response = await client.get("http://localhost:18201/memory/events")
            worker_memory = response.json()
            
            assert worker_memory["total"] > initial_count
            
            # Check worker has the task in its memory
            user_msgs = [e for e in worker_memory["events"] if e["event_type"] == "user_message"]
            assert any(task_id in str(e["content"]) for e in user_msgs)
    
    finally:
        pf_coordinator.terminate()
        pf_coordinator.wait(timeout=5)
        pf_worker1.terminate()
        pf_worker1.wait(timeout=5)


@pytest.mark.asyncio
async def test_multi_agent_process_independently(test_namespace: str):
    """Test each agent processes tasks independently with memory isolation."""
    resources = create_multi_agent_resources(test_namespace)
    
    # Deploy resources
    create_custom_resource(resources["modelapi"], test_namespace)
    wait_for_deployment(test_namespace, "modelapi-multi-agent-api", timeout=120)
    
    for agent_name in ["worker-1", "worker-2"]:
        create_custom_resource(resources[agent_name], test_namespace)
        wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    
    # Port forward to workers
    pf_w1 = port_forward(
        namespace=test_namespace,
        service_name="agent-worker-1",
        local_port=18300,
        remote_port=8000,
    )
    pf_w2 = port_forward(
        namespace=test_namespace,
        service_name="agent-worker-2",
        local_port=18301,
        remote_port=8000,
    )
    
    time.sleep(2)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Send unique tasks
            task1_id = f"W1_TASK_{int(time.time())}"
            task2_id = f"W2_TASK_{int(time.time())}"
            
            # Invoke worker-1
            response = await client.post(
                "http://localhost:18300/agent/invoke",
                json={"task": f"Process task {task1_id}"}
            )
            assert response.status_code == 200
            
            # Invoke worker-2
            response = await client.post(
                "http://localhost:18301/agent/invoke",
                json={"task": f"Process task {task2_id}"}
            )
            assert response.status_code == 200
            
            # Verify memory isolation
            response = await client.get("http://localhost:18300/memory/events")
            w1_memory = response.json()
            w1_content = " ".join(str(e["content"]) for e in w1_memory["events"])
            
            response = await client.get("http://localhost:18301/memory/events")
            w2_memory = response.json()
            w2_content = " ".join(str(e["content"]) for e in w2_memory["events"])
            
            # Each worker should have its own task, not the other's
            assert task1_id in w1_content
            assert task2_id not in w1_content
            assert task2_id in w2_content
            assert task1_id not in w2_content
    
    finally:
        pf_w1.terminate()
        pf_w1.wait(timeout=5)
        pf_w2.terminate()
        pf_w2.wait(timeout=5)
