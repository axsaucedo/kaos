"""
FastMCP Code Mode Server - Python tools with CodeMode transform.

Loads Python functions from MCP_TOOLS_STRING and exposes them through
FastMCP's CodeMode transform, providing meta-tools (search, get_schema,
execute) instead of individual tool schemas.
"""

import os
from types import FunctionType
from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode

mcp = FastMCP("FastMCP CodeMode Server", transforms=[CodeMode()])

tools_string = os.getenv("MCP_TOOLS_STRING", "")
if tools_string:
    namespace = {}
    exec(tools_string, {}, namespace)
    for name, func in namespace.items():
        if isinstance(func, FunctionType):
            mcp.tool(name)(func)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
