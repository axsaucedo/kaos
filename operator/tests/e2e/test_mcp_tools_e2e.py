"""End-to-end tests for MCP tool integration in Kubernetes.

Tests the MCP server and agent tool calling via Gateway API:
- MCPServer deployment with dynamic tools (Streamable HTTP transport)
- Agent connects to MCPServer and discovers tools via MCP protocol
- Tool calling via DEBUG_MOCK_RESPONSES (agent decides to call tool)
- Memory verification for tool call events
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


def create_echo_mcp_server(namespace: str, name: str = "echo-mcp"):
    """Create an MCPServer with echo tool using tools.fromString."""
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "type": "python-runtime",
            "config": {
                "tools": {
                    "fromString": '''
def echo(message: str) -> str:
    """Echo the provided message back."""
    return f"Echo: {message}"

def reverse(text: str) -> str:
    """Reverse the provided text."""
    return text[::-1]
'''
                },
                "env": [{"name": "MCP_LOG_LEVEL", "value": "INFO"}],
            },
        },
    }


def create_agent_with_mcp(
    namespace: str,
    modelapi_name: str,
    mcp_server_name: str,
    agent_name: str = "mcp-agent",
    mock_responses: list = None,
):
    """Create an Agent connected to an MCPServer.

    Args:
        mock_responses: List of mock responses for DEBUG_MOCK_RESPONSES.
                       Use tool_call block to trigger tool calling.
    """
    env = [
        {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
    ]
    if mock_responses:
        env.append(
            {"name": "DEBUG_MOCK_RESPONSES", "value": json.dumps(mock_responses)}
        )

    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "model": "gpt-3.5-turbo",  # Required: must match ModelAPI's models
            "mcpServers": [mcp_server_name],
            "config": {
                "description": "Agent with MCP tools",
                "instructions": "You have access to echo and reverse tools. Use them to help users.",
                "reasoningLoopMaxSteps": 5,
                "env": env,
            },
            "agentNetwork": {"access": []},
        },
    }


@pytest.mark.asyncio
async def test_mcpserver_deployment_and_health(test_namespace: str):
    """Test MCPServer deploys and is healthy."""
    mcp_name = "mcp-health"
    mcp_spec = create_echo_mcp_server(test_namespace, mcp_name)

    create_custom_resource(mcp_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp_name}", timeout=120)

    mcp_url = gateway_url(test_namespace, "mcp", mcp_name)
    wait_for_resource_ready(mcp_url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Health check
        response = await client.get(f"{mcp_url}/health")
        assert response.status_code == 200
        health = response.json()
        assert health.get("status") == "healthy"

        # Ready check - also shows registered tools
        response = await client.get(f"{mcp_url}/ready")
        assert response.status_code == 200
        ready = response.json()
        assert ready.get("status") == "ready"
        assert "echo" in ready.get("tools", [])
        assert "reverse" in ready.get("tools", [])


@pytest.mark.asyncio
async def test_mcpserver_ready_shows_tools(test_namespace: str):
    """Test MCPServer /ready endpoint shows registered tools."""
    mcp_name = "mcp-ready"
    mcp_spec = create_echo_mcp_server(test_namespace, mcp_name)

    create_custom_resource(mcp_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp_name}", timeout=120)

    mcp_url = gateway_url(test_namespace, "mcp", mcp_name)
    wait_for_resource_ready(mcp_url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{mcp_url}/ready")
        assert response.status_code == 200
        ready = response.json()

        # Verify tools are listed
        tools = ready.get("tools", [])
        assert "echo" in tools, f"echo not in tools: {tools}"
        assert "reverse" in tools, f"reverse not in tools: {tools}"


@pytest.mark.asyncio
async def test_agent_with_mcp_tools_discovery(
    test_namespace: str, shared_modelapi: str
):
    """Test Agent can discover tools from MCPServer via MCP protocol."""
    mcp_name = "mcp-agent-disc"
    agent_name = "mcp-test-agent"

    # Deploy MCPServer
    mcp_spec = create_echo_mcp_server(test_namespace, mcp_name)
    create_custom_resource(mcp_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp_name}", timeout=120)

    mcp_url = gateway_url(test_namespace, "mcp", mcp_name)
    wait_for_resource_ready(mcp_url)

    # Deploy Agent connected to MCPServer (no mock responses - just testing discovery)
    agent_spec = create_agent_with_mcp(
        test_namespace, shared_modelapi, mcp_name, agent_name
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)

    # Use async helper with retries to handle transient 503s from gateway
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Verify agent is healthy
        response = await client.get(f"{agent_url}/health")
        assert response.status_code == 200

        # Verify agent card has tool_execution capability
        response = await client.get(f"{agent_url}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        assert (
            "tool_execution" in card["capabilities"]
        ), f"Expected tool_execution capability, got: {card['capabilities']}"

        # Verify agent discovered tools (shown in skills)
        skills = card.get("skills", [])
        skill_names = [s.get("name") for s in skills]
        assert "echo" in skill_names, f"echo not in skills: {skill_names}"
        assert "reverse" in skill_names, f"reverse not in skills: {skill_names}"


@pytest.mark.asyncio
async def test_agent_tool_calling_with_memory(
    test_namespace: str, shared_modelapi: str
):
    """Test Agent calls MCP tool and memory tracks the event.

    Uses DEBUG_MOCK_RESPONSES to trigger a tool call, then verifies:
    - Tool call is executed via MCP protocol
    - Memory has tool_call and tool_result events
    """
    task_id = f"TOOL_{int(time.time())}"
    mcp_name = "mcp-tool-call"
    agent_name = "mcp-tool-agent"

    # Deploy MCPServer
    mcp_spec = create_echo_mcp_server(test_namespace, mcp_name)
    create_custom_resource(mcp_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp_name}", timeout=120)

    mcp_url = gateway_url(test_namespace, "mcp", mcp_name)
    wait_for_resource_ready(mcp_url)

    # Deploy Agent with mock response that triggers tool call
    mock_responses = [
        f"""I'll use the echo tool to help you.
```tool_call
{{"tool": "echo", "arguments": {{"message": "Task {task_id} processed"}}}}
```""",
        f"The echo tool returned the result for task {task_id}.",
    ]

    agent_spec = create_agent_with_mcp(
        test_namespace,
        shared_modelapi,
        mcp_name,
        agent_name,
        mock_responses=mock_responses,
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)

    # Use async helper with retries to handle transient 503s from gateway
    await async_wait_for_healthy(agent_url)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Send user message - mock response will trigger tool call
        response = await client.post(
            f"{agent_url}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Please process task {task_id} using the echo tool",
                    }
                ],
            },
        )

        assert response.status_code == 200, f"Request failed: {response.text}"
        data = response.json()
        assert "choices" in data
        assert len(data["choices"][0]["message"]["content"]) > 0

        # Verify memory has tool call events
        response = await client.get(f"{agent_url}/memory/events")
        assert response.status_code == 200
        memory = response.json()

        event_types = [e["event_type"] for e in memory["events"]]

        # Should have tool_call and tool_result events
        assert "tool_call" in event_types, f"Missing tool_call in events: {event_types}"
        assert (
            "tool_result" in event_types
        ), f"Missing tool_result in events: {event_types}"

        # Verify the tool call was for our task
        tool_calls = [e for e in memory["events"] if e["event_type"] == "tool_call"]
        assert any(
            task_id in str(e["content"]) for e in tool_calls
        ), f"Task {task_id} not found in tool call events"

        # Verify tool result contains the echo result
        tool_results = [e for e in memory["events"] if e["event_type"] == "tool_result"]
        assert any(
            "Echo:" in str(e["content"]) for e in tool_results
        ), f"Echo response not found in tool result events"


@pytest.mark.asyncio
async def test_agent_multiple_mcp_servers(test_namespace: str, shared_modelapi: str):
    """Test Agent can connect to multiple MCPServers."""
    mcp1_name = "mcp-multi-1"
    mcp2_name = "mcp-multi-2"
    agent_name = "mcp-multi-agent"

    # Create first MCPServer with echo
    mcp1_spec = create_echo_mcp_server(test_namespace, mcp1_name)
    create_custom_resource(mcp1_spec, test_namespace)

    # Create second MCPServer with different tool
    mcp2_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": mcp2_name, "namespace": test_namespace},
        "spec": {
            "type": "python-runtime",
            "config": {
                "tools": {
                    "fromString": '''
def uppercase(text: str) -> str:
    """Convert text to uppercase."""
    return text.upper()
'''
                },
                "env": [{"name": "MCP_LOG_LEVEL", "value": "INFO"}],
            },
        },
    }
    create_custom_resource(mcp2_spec, test_namespace)

    # Wait for both to be ready
    wait_for_deployment(test_namespace, f"mcpserver-{mcp1_name}", timeout=120)
    wait_for_deployment(test_namespace, f"mcpserver-{mcp2_name}", timeout=120)

    wait_for_resource_ready(gateway_url(test_namespace, "mcp", mcp1_name))
    wait_for_resource_ready(gateway_url(test_namespace, "mcp", mcp2_name))

    # Deploy Agent connected to both MCPServers
    agent_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": test_namespace},
        "spec": {
            "modelAPI": shared_modelapi,
            "model": "gpt-3.5-turbo",  # Required: must match ModelAPI's models
            "mcpServers": [mcp1_name, mcp2_name],  # Both MCP servers
            "config": {
                "description": "Agent with multiple MCP tools",
                "instructions": "You have access to echo, reverse, and uppercase tools.",
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "DEBUG"},
                ],
            },
            "agentNetwork": {"access": []},
        },
    }
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)

    # Use async helper with retries to handle transient 503s from gateway
    response = await async_wait_for_healthy(agent_url)
    assert response.status_code == 200

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Verify agent card has tool_execution capability
        response = await client.get(f"{agent_url}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        assert "tool_execution" in card["capabilities"]

        # Verify agent discovered tools from both servers
        skills = card.get("skills", [])
        skill_names = [s.get("name") for s in skills]
        assert "echo" in skill_names, f"echo not in skills: {skill_names}"
        assert "uppercase" in skill_names, f"uppercase not in skills: {skill_names}"
