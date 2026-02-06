"""End-to-end tests for pctx unified MCP server runtime.

Tests the pctx MCP aggregator:
- pctx deployment with upstream MCP servers
- Tool aggregation and discovery via pctx
- Tool execution through pctx code mode
- Agent integration with pctx server
"""

import asyncio
import json
import time
import pytest
import httpx

from e2e.conftest import (
    async_wait_for_healthy,
    create_custom_resource,
    wait_for_deployment,
    wait_for_resource_ready,
    gateway_url,
    wait_for_mcp_server_ready,
)


def create_upstream_mcp_server(namespace: str, name: str = "upstream-echo"):
    """Create an upstream MCPServer with python-string runtime for pctx to aggregate."""
    tools_code = '''def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

def multiply(x: int, y: int) -> int:
    """Multiply two numbers."""
    return x * y
'''
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "runtime": "python-string",
            "params": tools_code,
        },
    }


def create_pctx_server(namespace: str, upstream_names: list, name: str = "pctx-unified"):
    """Create a pctx MCPServer that aggregates upstream MCP servers.
    
    Args:
        namespace: Kubernetes namespace
        upstream_names: List of upstream MCPServer names to aggregate
        name: Name for this pctx server
    """
    servers = []
    for upstream_name in upstream_names:
        servers.append({
            "name": upstream_name.replace("-", "_"),  # pctx requires valid JS identifiers
            "url": f"http://mcpserver-{upstream_name}.{namespace}.svc.cluster.local:8000/mcp"
        })
    
    pctx_config = {
        "name": name,
        "version": "1.0.0",
        "servers": servers
    }
    
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "runtime": "pctx",
            "params": json.dumps(pctx_config),
        },
    }


def create_agent_with_pctx(
    namespace: str,
    modelapi_name: str,
    pctx_server_name: str,
    agent_name: str = "pctx-agent",
    mock_responses: list = None,
):
    """Create an Agent connected to a pctx MCPServer.

    Args:
        mock_responses: List of mock responses for DEBUG_MOCK_RESPONSES.
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
            "model": "gpt-3.5-turbo",
            "mcpServers": [pctx_server_name],
            "config": {
                "description": "Agent with pctx unified MCP server",
                "instructions": "You have access to tools through pctx code mode. Use them to help users with calculations.",
                "reasoningLoopMaxSteps": 5,
            },
            "container": {"env": env},
            "agentNetwork": {"access": []},
        },
    }


@pytest.mark.asyncio
async def test_pctx_deployment_ready(test_namespace: str):
    """Test pctx MCPServer deploys and is ready with upstream servers."""
    upstream_name = "pctx-upstream-1"
    pctx_name = "pctx-basic"
    
    # Deploy upstream MCP server first
    upstream_spec = create_upstream_mcp_server(test_namespace, upstream_name)
    create_custom_resource(upstream_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{upstream_name}", timeout=120)
    
    upstream_url = gateway_url(test_namespace, "mcp", upstream_name)
    await wait_for_mcp_server_ready(upstream_url, max_wait=60)
    
    # Deploy pctx server aggregating the upstream
    pctx_spec = create_pctx_server(test_namespace, [upstream_name], pctx_name)
    create_custom_resource(pctx_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{pctx_name}", timeout=120)
    
    # pctx exposes /mcp endpoint - verify it's reachable
    pctx_url = gateway_url(test_namespace, "mcp", pctx_name)
    await wait_for_mcp_server_ready(pctx_url, max_wait=60)


@pytest.mark.asyncio
async def test_agent_discovers_tools_via_pctx(test_namespace: str, shared_modelapi: str):
    """Test Agent discovers aggregated tools from pctx server."""
    upstream_name = "pctx-tools-upstream"
    pctx_name = "pctx-tools"
    agent_name = "pctx-disc-agent"
    
    # Deploy upstream MCP server
    upstream_spec = create_upstream_mcp_server(test_namespace, upstream_name)
    create_custom_resource(upstream_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{upstream_name}", timeout=120)
    
    upstream_url = gateway_url(test_namespace, "mcp", upstream_name)
    await wait_for_mcp_server_ready(upstream_url, max_wait=60)
    
    # Deploy pctx server
    pctx_spec = create_pctx_server(test_namespace, [upstream_name], pctx_name)
    create_custom_resource(pctx_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{pctx_name}", timeout=120)
    
    pctx_url = gateway_url(test_namespace, "mcp", pctx_name)
    await wait_for_mcp_server_ready(pctx_url, max_wait=60)
    
    # Deploy Agent connected to pctx
    agent_spec = create_agent_with_pctx(
        test_namespace, shared_modelapi, pctx_name, agent_name
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    
    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Verify agent card has tool_execution capability
        response = await client.get(f"{agent_url}/.well-known/agent")
        assert response.status_code == 200
        card = response.json()
        assert "tool_execution" in card["capabilities"], \
            f"Expected tool_execution capability, got: {card['capabilities']}"
        
        # Verify agent discovered tools from pctx (code mode exposes code_mode tool)
        skills = card.get("skills", [])
        skill_names = [s.get("name") for s in skills]
        # pctx provides code_mode as primary tool
        assert len(skills) > 0, f"Expected at least one skill, got: {skills}"


@pytest.mark.asyncio
async def test_pctx_tool_execution_with_memory(test_namespace: str, shared_modelapi: str):
    """Test Agent executes tools through pctx and memory tracks the events.

    Uses DEBUG_MOCK_RESPONSES to trigger a tool call through pctx.
    """
    task_id = f"PCTX_{int(time.time())}"
    upstream_name = "pctx-exec-upstream"
    pctx_name = "pctx-exec"
    agent_name = "pctx-exec-agent"
    
    # Deploy upstream MCP server
    upstream_spec = create_upstream_mcp_server(test_namespace, upstream_name)
    create_custom_resource(upstream_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{upstream_name}", timeout=120)
    
    upstream_url = gateway_url(test_namespace, "mcp", upstream_name)
    await wait_for_mcp_server_ready(upstream_url, max_wait=60)
    
    # Deploy pctx server
    pctx_spec = create_pctx_server(test_namespace, [upstream_name], pctx_name)
    create_custom_resource(pctx_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{pctx_name}", timeout=120)
    
    pctx_url = gateway_url(test_namespace, "mcp", pctx_name)
    await wait_for_mcp_server_ready(pctx_url, max_wait=60)
    
    # Mock responses for tool call through pctx code_mode
    # pctx exposes code_mode tool that executes TypeScript code
    mock_responses = [
        f'{{"tool": "code_mode", "arguments": {{"code": "const result = await pctx_exec_upstream.add_numbers({{a: 5, b: 3}}); console.log(result);"}}}}',
        "{}",
        f"The calculation for task {task_id} completed. 5 + 3 = 8.",
    ]
    
    # Deploy Agent with mock responses
    agent_spec = create_agent_with_pctx(
        test_namespace, shared_modelapi, pctx_name, agent_name, mock_responses
    )
    create_custom_resource(agent_spec, test_namespace)
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)
    
    agent_url = gateway_url(test_namespace, "agent", agent_name)
    wait_for_resource_ready(agent_url)
    await async_wait_for_healthy(agent_url)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Send user message
        response = await client.post(
            f"{agent_url}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Calculate 5 + 3 for task {task_id}",
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
        
        # Should have tool_call event (for code_mode)
        assert "tool_call" in event_types, f"Missing tool_call in events: {event_types}"


@pytest.mark.asyncio
async def test_pctx_aggregates_multiple_upstreams(test_namespace: str):
    """Test pctx can aggregate multiple upstream MCP servers."""
    upstream1_name = "pctx-multi-up1"
    upstream2_name = "pctx-multi-up2"
    pctx_name = "pctx-multi"
    
    # First upstream - math operations
    upstream1_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": upstream1_name, "namespace": test_namespace},
        "spec": {
            "runtime": "python-string",
            "params": '''def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
''',
        },
    }
    
    # Second upstream - string operations
    upstream2_spec = {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": upstream2_name, "namespace": test_namespace},
        "spec": {
            "runtime": "python-string",
            "params": '''def uppercase(text: str) -> str:
    """Convert text to uppercase."""
    return text.upper()
''',
        },
    }
    
    # Deploy both upstreams
    create_custom_resource(upstream1_spec, test_namespace)
    create_custom_resource(upstream2_spec, test_namespace)
    
    wait_for_deployment(test_namespace, f"mcpserver-{upstream1_name}", timeout=120)
    wait_for_deployment(test_namespace, f"mcpserver-{upstream2_name}", timeout=120)
    
    await wait_for_mcp_server_ready(gateway_url(test_namespace, "mcp", upstream1_name), max_wait=60)
    await wait_for_mcp_server_ready(gateway_url(test_namespace, "mcp", upstream2_name), max_wait=60)
    
    # Deploy pctx aggregating both upstreams
    pctx_spec = create_pctx_server(test_namespace, [upstream1_name, upstream2_name], pctx_name)
    create_custom_resource(pctx_spec, test_namespace)
    wait_for_deployment(test_namespace, f"mcpserver-{pctx_name}", timeout=120)
    
    # Verify pctx is ready with both upstreams
    pctx_url = gateway_url(test_namespace, "mcp", pctx_name)
    await wait_for_mcp_server_ready(pctx_url, max_wait=60)
