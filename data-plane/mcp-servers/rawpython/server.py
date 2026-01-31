"""
RawPython MCP Server - Execute Python code strings as MCP tools.

This MCP server loads Python functions from the MCP_TOOLS_STRING environment
variable and exposes them as MCP tools via streamable HTTP.
"""

import os
from types import FunctionType
from fastmcp import FastMCP

mcp = FastMCP("RawPython MCP Server")

tools_string = os.getenv("MCP_TOOLS_STRING", "")
if tools_string:
    namespace = {}
    exec(tools_string, {}, namespace)
    for name, func in namespace.items():
        if isinstance(func, FunctionType):
            mcp.tool(name)(func)


def create_app():
    """Create ASGI app with health endpoint."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route, Mount

    async def health(_):
        return JSONResponse({"status": "healthy"})

    async def ready(_):
        # Return list of registered tools
        tool_names = list(mcp._tool_manager._tools.keys()) if hasattr(mcp, '_tool_manager') else []
        return JSONResponse({"status": "ready", "tools": tool_names})

    # Get the FastMCP app
    fastmcp_app = mcp.http_app()

    # Create wrapper app with health route and mount FastMCP
    app = Starlette(routes=[
        Route("/health", health),
        Route("/ready", ready),
        Mount("/", app=fastmcp_app),
    ])
    return app


# Export the app for uvicorn
app = create_app()
