"""
MCP Client using the official MCP SDK for protocol-compliant communication.

This client uses the MCP SDK's Streamable HTTP client to connect to any
MCP-compliant server (FastMCP servers, external MCP servers, etc.).
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp import types as mcp_types

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """MCP Tool representation with standard inputSchema format."""

    name: str
    description: str
    input_schema: Dict[str, Any]

    def __str__(self) -> str:
        return f"Tool({self.name}: {self.description})"

    @classmethod
    def from_mcp_tool(cls, mcp_tool: mcp_types.Tool) -> "Tool":
        """Create Tool from MCP SDK Tool type."""
        return cls(
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            input_schema=mcp_tool.inputSchema if mcp_tool.inputSchema else {},
        )


class MCPClient:
    """MCP client using the official MCP SDK for protocol-compliant communication.

    This client uses the MCP SDK's Streamable HTTP client to connect to any
    MCP-compliant server. It provides graceful degradation for unavailable
    servers with auto-retry on failure.

    The client connects to the standard MCP endpoint (typically /mcp) and uses
    JSON-RPC over Streamable HTTP for tool discovery and execution.
    """

    TIMEOUT = 5.0  # Short timeout - MCP servers should respond quickly

    def __init__(self, name: str, url: str):
        """Initialize MCPClient.

        Args:
            name: Name of the MCP server (for logging/identification)
            url: Base URL of the MCP server (e.g., 'http://localhost:8000')
                 The /mcp endpoint is automatically appended if not present.
        """
        self.name = name
        self.url = url.rstrip("/")

        # Ensure URL ends with /mcp for Streamable HTTP transport endpoint
        if not self.url.endswith("/mcp"):
            self._mcp_url = f"{self.url}/mcp"
        else:
            self._mcp_url = self.url

        self._tools: Dict[str, Tool] = {}
        self._active = False
        logger.info(f"MCPClient initialized: {self.name} -> {self._mcp_url}")

    @asynccontextmanager
    async def _connect(self):
        """Create a connection to the MCP server via Streamable HTTP."""
        async with streamable_http_client(self._mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def _init(self) -> bool:
        """Discover tools from MCP server. Returns True if successful."""
        try:
            async with self._connect() as session:
                result = await session.list_tools()

                self._tools = {}
                for mcp_tool in result.tools:
                    try:
                        self._tools[mcp_tool.name] = Tool.from_mcp_tool(mcp_tool)
                    except Exception as e:
                        logger.warning(f"Failed to parse tool {mcp_tool.name}: {e}")

                self._active = True
                logger.info(f"MCPClient {self.name} active with {len(self._tools)} tools")
                return True

        except Exception as e:
            self._active = False
            logger.warning(f"MCPClient {self.name} init failed: {type(e).__name__}: {e}")
            return False

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None) -> Any:
        """Call a tool on the MCP server.

        Args:
            name: Name of the tool to call
            args: Arguments to pass to the tool

        Returns:
            Tool result (text content or structured content)

        Raises:
            RuntimeError: If server is unavailable
            ValueError: If tool is not found
        """
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"MCP server {self.name} unavailable at {self._mcp_url}")

        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found. Available: {list(self._tools.keys())}")

        try:
            async with self._connect() as session:
                result = await session.call_tool(name, args or {})

                # Extract result from CallToolResult
                # Prefer structured content if available
                if result.structuredContent:
                    return result.structuredContent
                elif result.content:
                    # Return text content from first content block
                    for content in result.content:
                        if hasattr(content, "text"):
                            return {"result": content.text}
                    return {"result": str(result.content)}
                else:
                    return {"result": None}

        except Exception as e:
            self._active = False
            raise RuntimeError(f"Tool {name}: {type(e).__name__}: {e}")

    def get_tools(self) -> List[Tool]:
        """Get list of discovered tools."""
        return list(self._tools.values())

    async def close(self):
        """Close client (no-op for connection-per-request pattern)."""
        # The MCP SDK uses context managers for connections,
        # so there's nothing to close here.
        pass
