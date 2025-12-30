import json
import logging
from types import FunctionType
from typing import Dict, Any, Callable, List, Optional, Literal
from fastmcp import FastMCP
import uvicorn
from fastmcp.server.http import StarletteWithLifespan
from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


class MCPServerSettings(BaseSettings):
    """Agent server configuration from environment variables."""

    # Required settings
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8002
    mcp_tools_string: str = ""


class MCPServer:
    """Secure MCP server that hosts tools via FastMCP protocol."""

    def __init__(self, settings: MCPServerSettings):
        """Initialize MCP server."""
        self._host = settings.mcp_host
        self._port = settings.mcp_port
        self.mcp = FastMCP("Dynamic MCP Server")
        self.tools_registry: Dict[str, Callable] = {}

        # Register provided tools
        if settings.mcp_tools_string:
            self.register_tools_from_string(settings.mcp_tools_string)

        logger.info(f"MCPServer initialized on port {self._port} with {len(self.tools_registry)} tools")

    def register_tools(self, tools: Dict[str, Callable]):
        """Register multiple tools with the MCP server.

        Args:
            tools: Dictionary mapping tool names to callable functions
        """
        for name, func in tools.items():
            if not name or not name.replace('_', '').replace('-', '').isalnum():
                raise ValueError(f"Tool name '{name}' contains invalid characters")

            try:
                self.tools_registry[name] = func
                self.mcp.tool(name)(func)
                logger.info(f"Registered tool: {name}")

            except Exception as e:
                logger.error(f"Failed to register tool {name}: {e}")
                # Remove from registry if registration failed
                self.tools_registry.pop(name, None)
                raise

    def register_tools_from_string(self, tools_string: str):
        if not tools_string or not tools_string.strip():
            logger.info("No tools string provided")
            return

        namespace: Dict[str, object] = {}
        exec(tools_string, {}, namespace)
        tools = {name: obj for name, obj in namespace.items() if isinstance(obj, FunctionType)}
        self.register_tools(tools)


    def get_registered_tools(self) -> List[str]:
        """Get list of registered tool names.

        Returns:
            List of tool names
        """
        return list(self.tools_registry.keys())

    def create_app(self, transport: Literal["http", "streamable-http", "sse"] = "http") -> StarletteWithLifespan:
        """Create FastMCP ASGI app using the http_app creation that returns a starlette app."""
        return self.mcp.http_app(transport=transport)

    def run(self, transport: Literal["http", "streamable-http", "sse"] = "http") -> None:
        """Run the MCP server through the FastMCP run command."""
        logger.info(f"Starting MCP server on {self._host}:{self._port} with tools: {self.get_registered_tools()}")
        self.mcp.run(host=self._host, port=self._port, transport=transport)


