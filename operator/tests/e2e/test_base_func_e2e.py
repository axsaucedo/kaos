"""End-to-end tests for Kubernetes operator deployment.

Tests the agent server running in Kubernetes with the new framework:
- Health/Ready endpoints
- Agent card at /.well-known/agent
- Task invocation with memory verification (using mock_response)
- Chat completions (streaming and non-streaming)
"""

import time
import subprocess
import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    port_forward,
    create_modelapi_resource,
    create_mcpserver_resource,
    create_agent_resource,
)


@pytest.mark.asyncio
async def test_agent_health_discovery_and_invocation(test_namespace: str):
    """Test complete agent workflow: health, discovery, invocation with mock_response."""
    # Create resources - using mock proxy (no real LLM needed)
    modelapi_spec = create_modelapi_resource(test_namespace, "mock-proxy")
    create_custom_resource(modelapi_spec, test_namespace)
    
    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name="mock-proxy",
        mcpserver_names=[],
        agent_name="test-agent",
    )
    create_custom_resource(agent_spec, test_namespace)

    wait_for_deployment(test_namespace, "modelapi-mock-proxy", timeout=120)
    wait_for_deployment(test_namespace, "agent-test-agent", timeout=120)

    pf_process = port_forward(
        namespace=test_namespace,
        service_name="agent-test-agent",
        local_port=18000,
        remote_port=8000,
    )

    time.sleep(2)
    agent_url = "http://localhost:18000"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. Health endpoint
            response = await client.get(f"{agent_url}/health")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"

            # 2. Ready endpoint
            response = await client.get(f"{agent_url}/ready")
            assert response.status_code == 200
            assert response.json()["status"] == "ready"

            # 3. Agent card at /.well-known/agent
            response = await client.get(f"{agent_url}/.well-known/agent")
            assert response.status_code == 200
            card = response.json()
            assert "name" in card
            assert "capabilities" in card
            assert "message_processing" in card["capabilities"]

            # 4. Invoke agent
            response = await client.post(
                f"{agent_url}/agent/invoke",
                json={"task": "Say hello briefly"},
            )
            assert response.status_code == 200
            result = response.json()
            assert "response" in result
            assert result["status"] == "completed"
            assert len(result["response"]) > 0

            # 5. Verify memory events
            response = await client.get(f"{agent_url}/memory/events")
            assert response.status_code == 200
            memory = response.json()
            assert memory["total"] >= 2  # user_message + agent_response
            
            event_types = [e["event_type"] for e in memory["events"]]
            assert "user_message" in event_types
            assert "agent_response" in event_types

    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)


@pytest.mark.asyncio
async def test_agent_chat_completions(test_namespace: str):
    """Test OpenAI-compatible chat completions endpoint with mock_response."""
    modelapi_spec = create_modelapi_resource(test_namespace, "mock-proxy")
    create_custom_resource(modelapi_spec, test_namespace)
    
    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name="mock-proxy",
        mcpserver_names=[],
        agent_name="chat-agent",
    )
    create_custom_resource(agent_spec, test_namespace)

    wait_for_deployment(test_namespace, "modelapi-mock-proxy", timeout=120)
    wait_for_deployment(test_namespace, "agent-chat-agent", timeout=120)

    pf_process = port_forward(
        namespace=test_namespace,
        service_name="agent-chat-agent",
        local_port=18001,
        remote_port=8000,
    )

    time.sleep(2)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Test non-streaming
            response = await client.post(
                "http://localhost:18001/v1/chat/completions",
                json={
                    "model": "chat-agent",
                    "messages": [{"role": "user", "content": "Say OK"}],
                    "stream": False
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

    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)
