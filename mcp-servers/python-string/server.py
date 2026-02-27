"""
Python-String MCP Server - Execute Python code strings as MCP tools.

This MCP server loads Python functions from the MCP_TOOLS_STRING environment
variable and exposes them as MCP tools via streamable HTTP.
"""

import os
from types import FunctionType
from fastmcp import FastMCP

mcp = FastMCP("Python-String MCP Server")

tools_string = os.getenv("MCP_TOOLS_STRING", "")
if tools_string:
    namespace = {}
    exec(tools_string, {}, namespace)
    for name, func in namespace.items():
        if isinstance(func, FunctionType):
            mcp.tool(name)(func)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
