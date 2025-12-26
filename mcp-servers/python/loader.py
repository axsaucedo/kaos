"""
MCP Server Loader and Registry.

This is the main entry point for the MCP servers. It loads and manages
multiple MCP servers based on environment configuration and exposes
them through a unified HTTP API.

Philosophy: Uses externally-maintained, proven MCP servers to:
- Reduce maintenance burden
- Leverage community-reviewed implementations
- Ensure security through proven packages
- Simplify operations (fewer Docker images to manage)

Security First: Only safe, externally-maintained, proven servers are enabled.

Default: calculator (mcp-server-calculator) - safe arithmetic operations
"""

import os
import logging
from typing import Dict, Any, List
from importlib import import_module

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MCP Servers",
    description="MCP Server Registry for Agentic Kubernetes Operator",
    version="0.1.0"
)

# Registry of available MCP servers
# Uses proven, externally-maintained MCP servers for safety and simplicity
SAFE_SERVERS = {
    "calculator": "mcp_server_calculator",  # External: pip install mcp-server-calculator
    # Add more proven servers here as needed
}

# Loaded server instances
_loaded_servers: Dict[str, Any] = {}


class ToolDefinition(BaseModel):
    """Tool definition for MCP tool"""
    name: str
    description: str
    parameters: Dict[str, Any]


class ToolInput(BaseModel):
    """Tool execution input"""
    tool_name: str
    input: Dict[str, Any]


class ToolResult(BaseModel):
    """Tool execution result"""
    success: bool
    result: Any
    error: str = ""


def load_server(server_name: str) -> Any:
    """
    Load a safe MCP server by name.

    Uses externally-maintained, proven MCP servers to avoid maintenance burden
    and leverage community-reviewed implementations.

    Args:
        server_name: Name of the server to load

    Returns:
        Server instance/module

    Raises:
        ValueError: If server is not found or not safe
    """
    if server_name not in SAFE_SERVERS:
        raise ValueError(f"Unknown or unsafe server: {server_name}")

    if server_name in _loaded_servers:
        return _loaded_servers[server_name]

    try:
        module_name = SAFE_SERVERS[server_name]
        module = import_module(module_name)

        logger.info(f"Loaded external MCP server: {server_name} (module: {module_name})")
        _loaded_servers[server_name] = module
        return module

    except ImportError as e:
        logger.error(
            f"Failed to load server {server_name}: {e}. "
            f"Make sure it's installed via pip (e.g., pip install {module_name.replace('_', '-')})"
        )
        raise
    except Exception as e:
        logger.error(f"Failed to load server {server_name}: {e}")
        raise


def get_enabled_servers() -> List[str]:
    """
    Get list of enabled MCP servers from environment.

    Reads MCP_SERVERS env var (comma-separated list).
    Defaults to "calculator" (mcp-server-calculator).
    Only safe, externally-maintained servers are enabled.
    """
    mcp_servers = os.getenv("MCP_SERVERS", "calculator").split(",")
    enabled = []

    for server_name in mcp_servers:
        server_name = server_name.strip()
        if not server_name:
            continue

        if server_name not in SAFE_SERVERS:
            logger.warning(f"Server {server_name} is not in safe server list, skipping")
            continue

        try:
            load_server(server_name)
            enabled.append(server_name)
        except Exception as e:
            logger.error(f"Failed to enable server {server_name}: {e}")

    return enabled


@app.on_event("startup")
async def startup_event():
    """Initialize MCP servers on startup"""
    logger.info("Starting MCP Servers...")
    enabled = get_enabled_servers()
    logger.info(f"Enabled servers: {enabled}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "servers": get_enabled_servers()}


@app.get("/servers")
async def list_servers() -> Dict[str, List[str]]:
    """List all enabled servers"""
    return {"servers": get_enabled_servers()}


@app.get("/servers/{server_name}/tools")
async def get_server_tools(server_name: str) -> Dict[str, Any]:
    """
    Get tools exposed by a specific server.

    Returns:
    {
        "server": "server_name",
        "tools": [
            {
                "name": "tool_name",
                "description": "Tool description",
                "parameters": {...}
            }
        ]
    }
    """
    try:
        server = load_server(server_name)
        tools = server.get_tools() if hasattr(server, "get_tools") else []

        return {
            "server": server_name,
            "tools": tools
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tools")
async def list_all_tools() -> Dict[str, Any]:
    """List all tools from all enabled servers"""
    all_tools = {}

    for server_name in get_enabled_servers():
        try:
            server = load_server(server_name)
            tools = server.get_tools() if hasattr(server, "get_tools") else []
            all_tools[server_name] = tools
        except Exception as e:
            logger.error(f"Error listing tools from {server_name}: {e}")

    return {"tools": all_tools}


@app.post("/tools/execute")
async def execute_tool(request: ToolInput) -> ToolResult:
    """
    Execute a tool.

    Tool name format: "server_name.tool_name"

    Returns:
    {
        "success": true/false,
        "result": {...},
        "error": ""
    }
    """
    try:
        # Parse tool name
        parts = request.tool_name.split(".")
        if len(parts) != 2:
            return ToolResult(
                success=False,
                result=None,
                error="Invalid tool name format. Expected 'server.tool'"
            )

        server_name, tool_name = parts

        # Load server and execute tool
        server = load_server(server_name)
        result = server.execute_tool(tool_name, request.input)

        return ToolResult(success=True, result=result)

    except ValueError as e:
        return ToolResult(success=False, result=None, error=str(e))
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        return ToolResult(success=False, result=None, error=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
