"""
MCP Tool Integration Module.

Handles loading and integration of MCP (Model Context Protocol) servers
with the ADK Agent. Loads tools from remote MCP servers and converts
them to ADK Tool definitions.
"""

import os
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)


class MCPToolLoader:
    """Loads tools from remote MCP servers"""

    def __init__(self, mcp_servers_config: Optional[Dict[str, str]] = None):
        """Initialize MCP tool loader

        Args:
            mcp_servers_config: Optional pre-configured MCP servers. If not provided,
                              will load from environment variables.
        """
        if mcp_servers_config:
            self.mcp_servers = mcp_servers_config
        else:
            self.mcp_servers = self._load_mcp_config()
        self.tools_cache: Dict[str, Any] = {}

    def _load_mcp_config(self) -> Dict[str, str]:
        """Load MCP server configuration from environment variables"""
        config = {}

        # Parse MCP_SERVERS env var for server names
        mcp_names = os.getenv("MCP_SERVERS", "").split(",")

        for name in mcp_names:
            name = name.strip()
            if not name:
                continue

            # Look for MCP_SERVER_<NAME>_URL
            url_key = f"MCP_SERVER_{name.upper()}_URL"
            url = os.getenv(url_key)

            if url:
                config[name] = url
                logger.info(f"Loaded MCP server: {name} -> {url}")
            else:
                logger.warning(f"MCP server {name} configured but URL not found (missing {url_key})")

        return config

    async def load_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """
        Load tools from a specific MCP server.

        Args:
            server_name: Name of the MCP server to load tools from

        Returns:
            List of tool definitions
        """
        if server_name not in self.mcp_servers:
            logger.warning(f"MCP server {server_name} not configured")
            return []

        if server_name in self.tools_cache:
            return self.tools_cache[server_name]

        try:
            url = self.mcp_servers[server_name]
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{url}/tools", timeout=5.0)
                response.raise_for_status()
                tools = response.json().get("tools", [])

                self.tools_cache[server_name] = tools
                logger.info(f"Loaded {len(tools)} tools from {server_name}")
                return tools

        except Exception as e:
            logger.error(f"Failed to load tools from {server_name}: {e}")
            return []

    async def load_all_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load tools from all configured MCP servers"""
        all_tools = {}
        for server_name in self.mcp_servers:
            tools = await self.load_tools(server_name)
            if tools:
                all_tools[server_name] = tools
        return all_tools

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools from all MCP servers"""
        all_tools = []
        all_tools_by_server = await self.load_all_tools()
        for server_name, tools in all_tools_by_server.items():
            for tool in tools:
                # Add server name to tool for identification
                tool["server"] = server_name
                all_tools.append(tool)
        return all_tools

    async def execute_tool(
        self,
        server_name: str,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Any:
        """
        Execute a tool on a remote MCP server.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result
        """
        if server_name not in self.mcp_servers:
            raise ValueError(f"Unknown MCP server: {server_name}")

        try:
            url = self.mcp_servers[server_name]
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{url}/tools/execute",
                    json={"tool_name": tool_name, "input": tool_input},
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            raise


# Global loader instance
_tool_loader: Optional[MCPToolLoader] = None


def get_tool_loader() -> MCPToolLoader:
    """Get or create the global tool loader instance"""
    global _tool_loader
    if _tool_loader is None:
        _tool_loader = MCPToolLoader()
    return _tool_loader
