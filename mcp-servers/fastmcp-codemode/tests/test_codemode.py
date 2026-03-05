"""Tests for FastMCP CodeMode aggregator server."""

import json
import os

import pytest
from fastmcp import Client, FastMCP


def test_codemode_server_imports():
    """Verify core imports work."""
    from server import build_server, mcp

    assert mcp is not None
    assert callable(build_server)


def test_codemode_no_config(monkeypatch):
    """Server starts with no MCP_SERVERS_CONFIG — zero upstream servers."""
    monkeypatch.delenv("MCP_SERVERS_CONFIG", raising=False)
    from server import build_server

    mcp = build_server()
    assert mcp.name == "FastMCP CodeMode Aggregator"


def test_codemode_empty_servers(monkeypatch):
    """Server handles empty servers list."""
    monkeypatch.setenv("MCP_SERVERS_CONFIG", json.dumps({"servers": []}))
    from server import build_server

    mcp = build_server()
    assert mcp.name == "FastMCP CodeMode Aggregator"


@pytest.mark.asyncio
async def test_codemode_mounts_and_exposes_meta_tools():
    """Aggregator mounts upstream servers and exposes CodeMode meta-tools."""
    from fastmcp.experimental.transforms.code_mode import CodeMode

    upstream = FastMCP("Upstream")

    @upstream.tool
    def echo(msg: str) -> str:
        """Echo a message."""
        return msg

    aggregator = FastMCP("Test Aggregator", transforms=[CodeMode()])
    aggregator.mount(upstream, namespace="test")

    async with Client(aggregator) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert "search" in tool_names
        assert "get_schema" in tool_names
        assert "execute" in tool_names
        assert len(tool_names) == 3


@pytest.mark.asyncio
async def test_codemode_search_finds_namespaced_tools():
    """Search meta-tool discovers tools from mounted upstream servers."""
    from fastmcp.experimental.transforms.code_mode import CodeMode

    upstream = FastMCP("CalcServer")

    @upstream.tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    aggregator = FastMCP("Test Aggregator", transforms=[CodeMode()])
    aggregator.mount(upstream, namespace="calc")

    async with Client(aggregator) as client:
        result = await client.call_tool("search", {"query": "add numbers"})
        assert "calc_add" in str(result)
