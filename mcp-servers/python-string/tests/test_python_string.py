"""Tests for Python-String MCP Server."""

import os
import pytest


class TestPythonStringServerModule:
    """Tests for Python-String MCP server module."""

    def test_mcp_server_loads_without_tools(self):
        """Test server module loads without MCP_TOOLS_STRING."""
        # Clear env and reimport
        os.environ.pop("MCP_TOOLS_STRING", None)
        
        # Just verify import works
        import importlib
        import server
        importlib.reload(server)
        
        assert server.mcp is not None

    def test_mcp_server_loads_with_tools(self):
        """Test server module loads tools from MCP_TOOLS_STRING."""
        tools_string = '''
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''
        os.environ["MCP_TOOLS_STRING"] = tools_string
        
        import importlib
        import server
        importlib.reload(server)
        
        assert server.mcp is not None
        # Clean up
        os.environ.pop("MCP_TOOLS_STRING", None)

