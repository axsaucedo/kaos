"""
Consolidated MCP tools tests.

Tests MCPServer and MCPClient functionality including:
- Server creation with tools from string
- Health/ready endpoints
- Tool registry management
- MCP protocol communication via Streamable HTTP
"""

import pytest
import httpx
import time
import logging
from multiprocessing import Process

from mcptools.server import MCPServer, MCPServerSettings
from mcptools.client import MCPClient, Tool

logger = logging.getLogger(__name__)


def run_mcp_server(port: int, tools_string: str):
    """Run MCP server in subprocess with streamable-http transport."""
    settings = MCPServerSettings(
        mcp_port=port, mcp_tools_string=tools_string, mcp_log_level="WARNING"
    )
    server = MCPServer(settings)
    server.run(transport="streamable-http")


@pytest.fixture(scope="module")
def mcp_server_process():
    """Fixture that starts MCP server in subprocess."""
    port = 8050
    tools_string = '''
def echo(text: str) -> str:
    """Echo the input text back."""
    return f"Echo: {text}"

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def process_list(items: list) -> int:
    """Return the length of a list."""
    return len(items)

def format_dict(data: dict) -> str:
    """Format a dictionary as string."""
    return str(data)
'''

    process = Process(target=run_mcp_server, args=(port, tools_string))
    process.start()

    # Wait for server to be ready
    for _ in range(30):
        try:
            response = httpx.get(f"http://localhost:{port}/health", timeout=1.0)
            if response.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)

    yield {"url": f"http://localhost:{port}", "port": port}

    process.terminate()
    process.join(timeout=5)


class TestMCPServerCreation:
    """Tests for MCP server creation and tool registry."""

    def test_server_creation_and_tools_registry(self):
        """Test MCPServer can be created with tools from string and programmatically."""
        # Test tools from string
        tools_string = '''
def square(x: int) -> int:
    """Square a number."""
    return x * x

def greet(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"
'''
        settings = MCPServerSettings(mcp_port=9001, mcp_tools_string=tools_string)
        server = MCPServer(settings)

        # Verify tools are registered
        assert "square" in server.tools_registry
        assert "greet" in server.tools_registry
        assert server.tools_registry["square"](5) == 25
        assert server.tools_registry["greet"]("World") == "Hello, World!"

        # Test programmatic registration
        def custom_tool(x: int) -> int:
            """Custom tool."""
            return x * 10

        server.register_tools({"custom_tool": custom_tool})
        assert "custom_tool" in server.tools_registry
        assert server.tools_registry["custom_tool"](5) == 50

        # Test get_registered_tools
        tools = server.get_registered_tools()
        assert "square" in tools
        assert "greet" in tools
        assert "custom_tool" in tools

        logger.info("✓ Server creation and tools registry works correctly")

    def test_tools_string_edge_cases(self):
        """Test various edge cases for tools string parsing."""
        # Empty string
        settings = MCPServerSettings(mcp_port=9002, mcp_tools_string="")
        server = MCPServer(settings)
        assert len(server.tools_registry) == 0

        # Multiple tools
        tools_string = '''
def t1() -> str:
    """Tool 1."""
    return "t1"

def t2() -> str:
    """Tool 2."""
    return "t2"

def t3() -> str:
    """Tool 3."""
    return "t3"
'''
        settings2 = MCPServerSettings(mcp_port=9003, mcp_tools_string=tools_string)
        server2 = MCPServer(settings2)
        assert len(server2.tools_registry) == 3

        # Invalid syntax raises error
        with pytest.raises(SyntaxError):
            MCPServerSettings(mcp_port=9004, mcp_tools_string="def invalid syntax")
            MCPServer(MCPServerSettings(mcp_port=9004, mcp_tools_string="def invalid syntax"))

        logger.info("✓ Tools string edge cases handled correctly")

    def test_tools_with_various_types(self):
        """Test tools with different type annotations work correctly."""
        tools_string = '''
def string_tool(s: str) -> str:
    """String tool."""
    return s.upper()

def int_tool(n: int) -> int:
    """Int tool."""
    return n * 2

def list_tool(items: list) -> int:
    """List tool."""
    return len(items)

def dict_tool(data: dict) -> str:
    """Dict tool."""
    return str(data)
'''
        settings = MCPServerSettings(mcp_port=9005, mcp_tools_string=tools_string)
        server = MCPServer(settings)

        assert server.tools_registry["string_tool"]("hello") == "HELLO"
        assert server.tools_registry["int_tool"](5) == 10
        assert server.tools_registry["list_tool"]([1, 2, 3]) == 3
        assert "test" in server.tools_registry["dict_tool"]({"test": 1})

        logger.info("✓ Tools with various types work correctly")


class TestMCPServerEndpoints:
    """Tests for MCP server HTTP endpoints."""

    def test_server_health_and_ready_endpoints(self, mcp_server_process):
        """Test /health and /ready endpoints work correctly."""
        url = mcp_server_process["url"]

        # Health endpoint
        health_resp = httpx.get(f"{url}/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "healthy"
        assert health_data["tools"] >= 4  # echo, add, process_list, format_dict

        # Ready endpoint
        ready_resp = httpx.get(f"{url}/ready")
        assert ready_resp.status_code == 200
        ready_data = ready_resp.json()
        assert ready_data["status"] == "ready"
        assert "echo" in ready_data["tools"]
        assert "add" in ready_data["tools"]

        logger.info("✓ Health and ready endpoints work correctly")


class TestMCPClient:
    """Tests for MCP client functionality."""

    def test_client_creation_and_tool_model(self):
        """Test MCPClient creation and Tool model."""
        client = MCPClient(name="test-server", url="http://localhost:8002")

        assert client is not None
        assert client.name == "test-server"
        assert "localhost" in client._mcp_url
        assert client._mcp_url.endswith("/mcp")

        # Test Tool model with input_schema (MCP standard)
        tool = Tool(
            name="test_tool",
            description="A test tool",
            input_schema={
                "type": "object",
                "properties": {"param1": {"type": "string"}},
            },
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert "properties" in tool.input_schema

        logger.info("✓ Client creation and Tool model work correctly")


@pytest.mark.asyncio
class TestMCPClientServerIntegration:
    """Integration tests for MCPClient with MCPServer via MCP protocol."""

    async def test_client_discovers_tools_from_server(self, mcp_server_process):
        """Test MCPClient can discover tools via MCP protocol."""
        url = mcp_server_process["url"]

        client = MCPClient(name="test-server", url=url)

        # Initialize client (discovers tools via MCP protocol)
        result = await client._init()
        assert result is True
        assert client._active is True

        # Verify tools were discovered
        tools = client.get_tools()
        assert len(tools) >= 2
        tool_names = [t.name for t in tools]
        assert "echo" in tool_names
        assert "add" in tool_names

        # Verify input_schema format
        echo_tool = next(t for t in tools if t.name == "echo")
        assert "type" in echo_tool.input_schema
        assert echo_tool.input_schema["type"] == "object"

        await client.close()
        logger.info("✓ Client discovers tools from server correctly")

    async def test_client_calls_tool_on_server(self, mcp_server_process):
        """Test MCPClient can call tools via MCP protocol."""
        url = mcp_server_process["url"]

        client = MCPClient(name="test-server", url=url)

        # Call echo tool (uses 'text' parameter)
        result = await client.call_tool("echo", {"text": "Integration test"})
        assert "Integration test" in str(result)

        # Call add tool
        result = await client.call_tool("add", {"a": 10, "b": 5})
        assert result["result"] == 15

        await client.close()
        logger.info("✓ Client calls tools on server correctly")
