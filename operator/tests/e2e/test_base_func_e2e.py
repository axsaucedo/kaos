"""End-to-end tests for Kubernetes operator deployment.

Tests the agent server running in Kubernetes with the new framework:
- Health/Ready endpoints
- Agent card at /.well-known/agent
- Task invocation with memory verification (using Ollama)
- Chat completions (streaming and non-streaming)
"""

import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    port_forward_with_wait,
    create_modelapi_hosted_resource,
    create_agent_resource,
    get_next_port,
)


@pytest.mark.asyncio
async def test_agent_health_discovery_and_invocation(test_namespace: str):
    """Test complete agent workflow: health, discovery, invocation with actual Ollama."""
    # Create resources - using Ollama for actual model inference
    # Use unique names to allow parallel test execution
    modelapi_name = "base-ollama-proxy"
    agent_name = "base-test-agent"
    
    modelapi_spec = create_modelapi_hosted_resource(test_namespace, modelapi_name)
    create_custom_resource(modelapi_spec, test_namespace)
    
    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name=modelapi_name,
        mcpserver_names=[],
        agent_name=agent_name,
    )
    create_custom_resource(agent_spec, test_namespace)

    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=120)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    port = get_next_port()
    pf_process = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"agent-{agent_name}",
        local_port=port,
        remote_port=8000,
    )

    agent_url = f"http://localhost:{port}"

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
async def test_agent_chat_completions(test_namespace: str, shared_modelapi: str):
    """Test OpenAI-compatible chat completions endpoint with mock_response."""
    # Use shared ModelAPI for mock-based tests
    agent_name = "base-chat-agent"
    
    agent_spec = create_agent_resource(
        namespace=test_namespace,
        modelapi_name=shared_modelapi,
        mcpserver_names=[],
        agent_name=agent_name,
    )
    create_custom_resource(agent_spec, test_namespace)

    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    port = get_next_port()
    pf_process = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"agent-{agent_name}",
        local_port=port,
        remote_port=8000,
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Test non-streaming
            response = await client.post(
                f"http://localhost:{port}/v1/chat/completions",
                json={
                    "model": agent_name,
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
