"""E2E tests for documentation examples.

These tests validate that the examples in docs/examples/ work correctly.
They use the same fixtures as other E2E tests (gateway_setup, shared_namespace).
"""

import asyncio
import json
import time
from typing import Dict, Any

import httpx
import pytest
from sh import kubectl

from e2e.conftest import (
    GATEWAY_URL,
    create_custom_resource,
    create_modelapi_resource,
    gateway_url,
    wait_for_deployment,
    wait_for_resource_ready,
)


async def wait_for_mcp_server_ready(mcp_url: str, max_wait: int = 60):
    """Wait for MCPServer to be reachable via Gateway.
    
    MCPServer uses vanilla FastMCP which returns 400/406 for GET requests
    to /mcp endpoint (requires proper MCP protocol headers). This is expected
    and indicates the server is running.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        for _ in range(max_wait):
            try:
                response = await client.get(f"{mcp_url}/mcp")
                if response.status_code in [400, 406]:
                    return  # Server is running
            except Exception:
                pass
            await asyncio.sleep(1)
    raise TimeoutError(f"MCPServer not reachable at {mcp_url}/mcp after {max_wait}s")


class TestCustomMCPServerExample:
    """Tests for the Custom MCP Server example."""

    @pytest.mark.asyncio
    async def test_python_string_mcp_server(self, shared_namespace: str):
        """Test creating and using a custom MCP server with tools.
        
        This mirrors the docs/examples/custom-mcp-server.md example.
        """
        namespace = shared_namespace

        # Create ModelAPI
        modelapi_name = "example-api"
        modelapi_spec = create_modelapi_resource(namespace, modelapi_name)
        create_custom_resource(modelapi_spec, namespace)
        wait_for_deployment(namespace, f"modelapi-{modelapi_name}", timeout=120)

        # Create MCPServer with weather-like tools
        mcp_name = "weather-mcp"
        mcp_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "MCPServer",
            "metadata": {"name": mcp_name, "namespace": namespace},
            "spec": {
                "runtime": "python-string",
                "params": '''def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Weather in {city}: 22°C, sunny"

def convert_temperature(value: float, from_unit: str, to_unit: str) -> str:
    """Convert temperature between Celsius and Fahrenheit."""
    if from_unit.upper() == "C" and to_unit.upper() == "F":
        result = (value * 9/5) + 32
    elif from_unit.upper() == "F" and to_unit.upper() == "C":
        result = (value - 32) * 5/9
    else:
        return f"{value}°{from_unit}"
    return f"{value}°{from_unit.upper()} = {result:.1f}°{to_unit.upper()}"
''',
            },
        }
        create_custom_resource(mcp_spec, namespace)
        wait_for_deployment(namespace, f"mcpserver-{mcp_name}", timeout=120)

        # Wait for MCP to be accessible via Gateway (uses /mcp endpoint check)
        mcp_url = gateway_url(namespace, "mcp", mcp_name)
        await wait_for_mcp_server_ready(mcp_url, max_wait=60)

        # The MCP server is now running. To verify tools work, we'd need to
        # create an agent that uses this MCP server and check its agent card.
        # For this test, we just verify the server is deployed and reachable.
        
        # Verify via kubectl that MCPServer is Ready
        result = kubectl(
            "get", "mcpserver", mcp_name, "-n", namespace,
            "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}"
        )
        assert "True" in str(result), f"MCPServer not ready: {result}"


class TestKAOSMonkeyExample:
    """Tests for the KAOS Monkey example."""

    @pytest.mark.skip(reason="kubernetes runtime not available in default installation")
    @pytest.mark.asyncio
    async def test_kubernetes_mcp_runtime(self, shared_namespace: str):
        """Test the kubernetes MCP runtime for kubectl access.
        
        This mirrors the docs/examples/kaos-monkey.md example.
        Note: We test with limited permissions (get pods only).
        """
        namespace = shared_namespace

        # Create ModelAPI
        modelapi_name = "chaos-api"
        modelapi_spec = create_modelapi_resource(namespace, modelapi_name)
        create_custom_resource(modelapi_spec, namespace)
        wait_for_deployment(namespace, f"modelapi-{modelapi_name}", timeout=120)

        # Create a ServiceAccount for limited K8s access
        sa_spec = {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": "kaos-monkey-sa", "namespace": namespace},
        }
        create_custom_resource(sa_spec, namespace)

        # Create Role with limited permissions (get pods only)
        role_spec = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": {"name": "kaos-monkey-role", "namespace": namespace},
            "rules": [
                {
                    "apiGroups": [""],
                    "resources": ["pods"],
                    "verbs": ["get", "list"],
                }
            ],
        }
        create_custom_resource(role_spec, namespace)

        # Create RoleBinding
        rb_spec = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": "kaos-monkey-binding", "namespace": namespace},
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": "kaos-monkey-sa",
                    "namespace": namespace,
                }
            ],
            "roleRef": {
                "kind": "Role",
                "name": "kaos-monkey-role",
                "apiGroup": "rbac.authorization.k8s.io",
            },
        }
        create_custom_resource(rb_spec, namespace)

        # Create MCPServer with kubernetes runtime
        mcp_name = "k8s-tools"
        mcp_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "MCPServer",
            "metadata": {"name": mcp_name, "namespace": namespace},
            "spec": {
                "runtime": "kubernetes",
                "serviceAccountName": "kaos-monkey-sa",
            },
        }
        create_custom_resource(mcp_spec, namespace)
        wait_for_deployment(namespace, f"mcpserver-{mcp_name}", timeout=120)

        # Wait for MCP to be accessible via Gateway
        mcp_url = gateway_url(namespace, "mcp", mcp_name)
        await wait_for_mcp_server_ready(mcp_url, max_wait=60)

        # Verify MCPServer is Ready via kubectl
        result = kubectl(
            "get", "mcpserver", mcp_name, "-n", namespace,
            "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}"
        )
        assert "True" in str(result), f"MCPServer not ready: {result}"

    @pytest.mark.asyncio
    async def test_agent_with_mock_responses(self, shared_namespace: str, shared_modelapi: str):
        """Test an agent with mock responses (no real LLM calls).
        
        This validates the DEBUG_MOCK_RESPONSES pattern used in examples.
        """
        namespace = shared_namespace
        modelapi_name = shared_modelapi

        # Create agent with mock response
        agent_name = "mock-agent"
        mock_responses = json.dumps([
            "This is a mocked response from the agent. No LLM was called!"
        ])
        
        agent_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": agent_name, "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "config": {
                    "description": "Test agent with mock responses",
                    "instructions": "You are a test agent.",
                },
                "container": {
                    "env": [
                        {"name": "DEBUG_MOCK_RESPONSES", "value": mock_responses}
                    ]
                },
                "agentNetwork": {"expose": True},
            },
        }
        create_custom_resource(agent_spec, namespace)
        wait_for_deployment(namespace, f"agent-{agent_name}", timeout=120)

        # Wait for agent to be accessible
        agent_url = gateway_url(namespace, "agent", agent_name)
        wait_for_resource_ready(agent_url, max_wait=60)

        # Test the agent
        response = httpx.post(
            f"{agent_url}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [{"role": "user", "content": "Hello!"}],
            },
            timeout=30.0,
        )
        assert response.status_code == 200
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        assert "mocked response" in content


class TestMultiAgentTelemetryExample:
    """Tests for the Multi-Agent Telemetry example."""

    def test_multi_agent_delegation(self, shared_namespace: str, shared_modelapi: str):
        """Test multi-agent delegation with mock responses.
        
        This mirrors the docs/examples/multi-agent-telemetry.md example.
        """
        namespace = shared_namespace
        modelapi_name = shared_modelapi

        # Create researcher agent
        researcher_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "researcher", "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "config": {
                    "description": "Research specialist",
                    "instructions": "You gather information.",
                },
                "container": {
                    "env": [
                        {
                            "name": "DEBUG_MOCK_RESPONSES",
                            "value": json.dumps(["Research findings: AI adoption is growing 40% YoY."]),
                        }
                    ]
                },
                "agentNetwork": {"expose": True},
            },
        }
        create_custom_resource(researcher_spec, namespace)

        # Create coordinator agent
        coordinator_mock = json.dumps([
            'Let me delegate to the researcher.\n\n```delegate\n{"agent": "researcher", "task": "Research AI trends"}\n```',
            "Based on the research: AI adoption is growing rapidly with 40% YoY growth.",
        ])
        
        coordinator_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "coordinator", "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "config": {
                    "description": "Coordinator agent",
                    "instructions": "You coordinate with specialist agents.",
                },
                "container": {
                    "env": [
                        {"name": "DEBUG_MOCK_RESPONSES", "value": coordinator_mock}
                    ]
                },
                "agentNetwork": {
                    "expose": True,
                    "access": ["researcher"],
                },
            },
        }
        create_custom_resource(coordinator_spec, namespace)

        # Wait for both agents
        wait_for_deployment(namespace, "agent-researcher", timeout=120)
        wait_for_deployment(namespace, "agent-coordinator", timeout=120)

        researcher_url = gateway_url(namespace, "agent", "researcher")
        coordinator_url = gateway_url(namespace, "agent", "coordinator")
        
        wait_for_resource_ready(researcher_url, max_wait=60)
        wait_for_resource_ready(coordinator_url, max_wait=60)

        # Test coordinator - it should delegate to researcher
        response = httpx.post(
            f"{coordinator_url}/v1/chat/completions",
            json={
                "model": "coordinator",
                "messages": [{"role": "user", "content": "What are the AI trends?"}],
            },
            timeout=60.0,
        )
        assert response.status_code == 200
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        # Final response should include synthesized info
        assert "40%" in content or "growing" in content.lower()

    def test_agent_memory_events(self, shared_namespace: str, shared_modelapi: str):
        """Test that agent memory tracks events correctly."""
        namespace = shared_namespace
        modelapi_name = shared_modelapi

        agent_name = "memory-test-agent"
        agent_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": agent_name, "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "config": {
                    "description": "Memory test agent",
                    "instructions": "You are helpful.",
                },
                "container": {
                    "env": [
                        {
                            "name": "DEBUG_MOCK_RESPONSES",
                            "value": json.dumps(["Hello! I'm here to help."]),
                        }
                    ]
                },
                "agentNetwork": {"expose": True},
            },
        }
        create_custom_resource(agent_spec, namespace)
        wait_for_deployment(namespace, f"agent-{agent_name}", timeout=120)

        agent_url = gateway_url(namespace, "agent", agent_name)
        wait_for_resource_ready(agent_url, max_wait=60)

        # Send a message
        response = httpx.post(
            f"{agent_url}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [{"role": "user", "content": "Hi there!"}],
            },
            timeout=30.0,
        )
        assert response.status_code == 200

        # Check memory events
        time.sleep(1)  # Allow memory to be updated
        response = httpx.get(f"{agent_url}/memory/events", timeout=10.0)
        assert response.status_code == 200
        events = response.json().get("events", [])
        
        # Should have at least user message and agent response events
        event_types = [e.get("event_type") for e in events]
        assert "user_message" in event_types
        assert "agent_response" in event_types
