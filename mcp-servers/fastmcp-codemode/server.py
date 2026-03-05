"""
FastMCP Code Mode Server - MCP server aggregator with CodeMode transform.

Aggregates multiple upstream KAOS MCP servers via HTTP proxy and wraps them
with FastMCP's CodeMode transform, providing meta-tools (search, get_schema,
execute) for cross-server tool chaining in a Python sandbox.

Configuration via MCP_SERVERS_CONFIG env var (JSON):
    {"servers": [{"name": "calc", "url": "http://mcpserver-calc:8000/mcp"}]}
"""

import json
import os
import logging

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.experimental.transforms.code_mode import CodeMode

logger = logging.getLogger(__name__)


def build_server() -> FastMCP:
    """Build the aggregator server from MCP_SERVERS_CONFIG."""
    mcp = FastMCP("FastMCP CodeMode Aggregator", transforms=[CodeMode()])

    config_str = os.getenv("MCP_SERVERS_CONFIG", "")
    if not config_str:
        logger.warning("MCP_SERVERS_CONFIG not set — no upstream servers mounted")
        return mcp

    config = json.loads(config_str)
    servers = config.get("servers", [])

    for srv in servers:
        name = srv["name"]
        url = srv["url"]
        proxy = create_proxy(url)
        mcp.mount(proxy, namespace=name)
        logger.info(f"Mounted upstream server '{name}' from {url}")

    return mcp


mcp = build_server()

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
