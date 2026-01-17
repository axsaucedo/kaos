import json
import logging
import sys
import time
from types import FunctionType
from typing import Dict, Any, Callable, List, Optional, Literal
from fastmcp import FastMCP
import uvicorn
from fastmcp.server.http import StarletteWithLifespan
from pydantic_settings import BaseSettings
from starlette.routing import Route
from starlette.responses import JSONResponse


def configure_logging(level: str = "INFO") -> None:
    """Configure logging for the application.

    Sets up a consistent logging format and ensures all application loggers
    are properly configured to output to stdout.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # Override any existing configuration
    )

    # Ensure our application loggers are at the right level
    for logger_name in ["mcptools", "mcptools.server", "mcptools.client"]:
        logging.getLogger(logger_name).setLevel(log_level)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(log_level)


logger = logging.getLogger(__name__)


class MCPServerSettings(BaseSettings):
    """Agent server configuration from environment variables."""

    # Required settings
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    mcp_tools_string: str = ""
    mcp_log_level: str = "INFO"
    mcp_access_log: bool = False  # Mute uvicorn access logs by default


class MCPServer:
    """Secure MCP server that hosts tools via FastMCP protocol."""

    def __init__(self, settings: MCPServerSettings):
        """Initialize MCP server."""
        # Configure logging first
        configure_logging(settings.mcp_log_level)

        self._host = settings.mcp_host
        self._port = settings.mcp_port
        self._log_level = settings.mcp_log_level
        self._access_log = settings.mcp_access_log
        self.mcp = FastMCP("Dynamic MCP Server")
        self.tools_registry: Dict[str, Callable] = {}

        # Register provided tools
        if settings.mcp_tools_string:
            self.register_tools_from_string(settings.mcp_tools_string)

    def _log_startup_config(self):
        """Log server configuration on startup for debugging."""
        logger.info("=" * 60)
        logger.info("MCPServer Starting")
        logger.info("=" * 60)
        logger.info(f"Host: {self._host}")
        logger.info(f"Port: {self._port}")
        logger.info(f"Log Level: {self._log_level}")
        logger.info(f"Access Log: {self._access_log}")
        logger.info(f"Tools Registered: {len(self.tools_registry)}")
        for tool_name in self.tools_registry:
            func = self.tools_registry[tool_name]
            doc = func.__doc__.split("\n")[0] if func.__doc__ else "No description"
            logger.info(f"  - {tool_name}: {doc}")
        logger.info("=" * 60)

    def register_tools(self, tools: Dict[str, Callable]):
        """Register multiple tools with the MCP server.

        Args:
            tools: Dictionary mapping tool names to callable functions
        """
        for name, func in tools.items():
            if not name or not name.replace("_", "").replace("-", "").isalnum():
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

    def create_app(
        self, transport: Literal["http", "streamable-http", "sse"] = "http"
    ) -> StarletteWithLifespan:
        """Create FastMCP ASGI app with health probes and REST tool endpoints."""
        mcp_app = self.mcp.http_app(transport=transport)

        async def health(request):
            return JSONResponse(
                {
                    "status": "healthy",
                    "tools": len(self.tools_registry),
                    "timestamp": int(time.time()),
                }
            )

        async def ready(request):
            return JSONResponse(
                {
                    "status": "ready",
                    "tools": self.get_registered_tools(),
                    "timestamp": int(time.time()),
                }
            )

        async def list_tools(request):
            """REST endpoint to list available tools (GET /mcp/tools)."""
            tools = []
            for name, func in self.tools_registry.items():
                # Build inputSchema from function annotations (MCP standard format)
                properties = {}
                required = []
                if hasattr(func, "__annotations__"):
                    for param_name, param_type in func.__annotations__.items():
                        if param_name != "return":
                            type_name = getattr(param_type, "__name__", str(param_type))
                            # Map Python types to JSON Schema types
                            json_type = {
                                "str": "string",
                                "int": "integer",
                                "float": "number",
                                "bool": "boolean",
                                "list": "array",
                                "dict": "object",
                            }.get(type_name, "string")
                            properties[param_name] = {"type": json_type}
                            required.append(param_name)

                input_schema = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }

                tools.append(
                    {
                        "name": name,
                        "description": (
                            func.__doc__.split("\n")[0] if func.__doc__ else "No description"
                        ),
                        "inputSchema": input_schema,
                    }
                )
            return JSONResponse({"tools": tools})

        async def call_tool(request):
            """REST endpoint to call a tool (POST /mcp/tools)."""
            try:
                body = await request.json()
                tool_name = body.get("tool")
                arguments = body.get("arguments", {})

                if not tool_name:
                    return JSONResponse({"error": "Missing 'tool' field"}, status_code=400)

                if tool_name not in self.tools_registry:
                    return JSONResponse(
                        {"error": f"Tool '{tool_name}' not found"},
                        status_code=404,
                    )

                func = self.tools_registry[tool_name]
                result = func(**arguments)

                return JSONResponse({"result": result})
            except json.JSONDecodeError:
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)
            except TypeError as e:
                return JSONResponse({"error": f"Invalid arguments: {e}"}, status_code=400)
            except Exception as e:
                logger.error(f"Tool call error: {e}")
                return JSONResponse({"error": str(e)}, status_code=500)

        async def mcp_tools_handler(request):
            """Handle both GET and POST for /mcp/tools."""
            if request.method == "GET":
                return await list_tools(request)
            elif request.method == "POST":
                return await call_tool(request)
            else:
                return JSONResponse({"error": "Method not allowed"}, status_code=405)

        # Prepend health routes and REST tool endpoint
        mcp_app.routes.insert(0, Route("/health", health))
        mcp_app.routes.insert(1, Route("/ready", ready))
        mcp_app.routes.insert(2, Route("/mcp/tools", mcp_tools_handler, methods=["GET", "POST"]))

        return mcp_app

    def run(self, transport: Literal["http", "streamable-http", "sse"] = "http") -> None:
        """Run the MCP server through the FastMCP run command."""
        self._log_startup_config()
        app = self.create_app(transport)
        try:
            uvicorn.run(
                app,
                host=self._host,
                port=self._port,
                log_level=self._log_level.lower(),
                access_log=self._access_log,
            )
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = MCPServerSettings()
    server = MCPServer(settings)
    server.run()
