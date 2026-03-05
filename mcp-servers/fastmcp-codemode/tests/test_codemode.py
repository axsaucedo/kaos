"""Tests for FastMCP Code Mode server."""

import os
import importlib

import pytest


def test_codemode_server_imports():
    """Verify server module imports without error."""
    import server

    assert server.mcp is not None
    assert server.mcp.name == "FastMCP CodeMode Server"


def test_codemode_loads_tools_from_env(monkeypatch):
    """Verify tools are loaded from MCP_TOOLS_STRING and wrapped by CodeMode."""
    monkeypatch.setenv(
        "MCP_TOOLS_STRING",
        'def add(a: int, b: int) -> int:\n    """Add."""\n    return a + b\n',
    )
    import server

    importlib.reload(server)
    assert server.mcp is not None


def test_codemode_empty_env(monkeypatch):
    """Verify server handles empty MCP_TOOLS_STRING gracefully."""
    monkeypatch.setenv("MCP_TOOLS_STRING", "")
    import server

    importlib.reload(server)
    assert server.mcp is not None


@pytest.mark.asyncio
async def test_codemode_exposes_meta_tools(monkeypatch):
    """Verify CodeMode exposes search/get_schema/execute instead of raw tools."""
    monkeypatch.setenv(
        "MCP_TOOLS_STRING",
        'def add(a: int, b: int) -> int:\n    """Add."""\n    return a + b\n'
        'def multiply(x: int, y: int) -> int:\n    """Multiply."""\n    return x * y\n',
    )
    import server

    importlib.reload(server)

    from fastmcp import Client

    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert "search" in tool_names
        assert "get_schema" in tool_names
        assert "execute" in tool_names
        # Raw tools should NOT be exposed directly
        assert "add" not in tool_names
        assert "multiply" not in tool_names
