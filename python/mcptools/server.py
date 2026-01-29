import logging
import os
import sys
import time
from types import FunctionType
from typing import Dict, Any, Callable, List, Literal
from fastmcp import FastMCP
import uvicorn
from fastmcp.server.http import StarletteWithLifespan
from pydantic_settings import BaseSettings
from starlette.routing import Route
from starlette.responses import JSONResponse


def get_log_level() -> str:
    """Get log level from environment, preferring LOG_LEVEL over MCP_LOG_LEVEL."""
    return os.getenv("LOG_LEVEL", os.getenv("MCP_LOG_LEVEL", "INFO")).upper()


def configure_logging(level: str = "INFO", otel_correlation: bool = False) -> None:
    """Configure logging for the application.

    Sets up a consistent logging format and ensures all application loggers
    are properly configured to output to stdout.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        otel_correlation: If True, include trace_id and span_id in log format
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Log format with optional OTel correlation
    if otel_correlation:
        log_format = (
            "%(asctime)s - %(name)s - %(levelname)s - "
            "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] - %(message)s"
        )
    else:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # Override any existing configuration
    )

    # If OTel correlation is enabled, add the LoggingInstrumentor
    if otel_correlation:
        try:
            from opentelemetry.instrumentation.logging import LoggingInstrumentor

            LoggingInstrumentor().instrument(set_logging_format=False)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to enable OTel log correlation: {e}")

    # Ensure our application loggers are at the right level
    for logger_name in ["mcptools", "mcptools.server", "mcptools.client"]:
        logging.getLogger(logger_name).setLevel(log_level)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(log_level)


logger = logging.getLogger(__name__)


class MCPServerSettings(BaseSettings):
    """MCP server configuration from environment variables."""

    # Required settings
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    mcp_tools_string: str = ""
    mcp_log_level: str = "INFO"
    mcp_access_log: bool = False  # Mute uvicorn access logs by default


class MCPServer:
    """MCP server that hosts tools via FastMCP Streamable HTTP protocol.

    Uses the standard MCP protocol with Streamable HTTP transport at /mcp endpoint.
    Tools can be registered programmatically or via fromString for dynamic creation.
    """

    def __init__(self, settings: MCPServerSettings):
        """Initialize MCP server."""
        # Check if OTel should be enabled using the shared utility
        # This requires both OTEL_SERVICE_NAME and OTEL_EXPORTER_OTLP_ENDPOINT
        from telemetry.manager import should_enable_otel

        otel_enabled = should_enable_otel()

        # Configure logging with optional OTel correlation
        # Use LOG_LEVEL env var (preferred) or fallback to MCP_LOG_LEVEL
        log_level = get_log_level()
        configure_logging(log_level, otel_correlation=otel_enabled)

        self._host = settings.mcp_host
        self._port = settings.mcp_port
        self._log_level = settings.mcp_log_level
        self._access_log = settings.mcp_access_log
        self._otel_enabled = otel_enabled
        self.mcp = FastMCP("Dynamic MCP Server")
        self.tools_registry: Dict[str, Callable] = {}

        # Initialize OpenTelemetry if enabled
        if otel_enabled:
            self._init_telemetry()

        # Register provided tools
        if settings.mcp_tools_string:
            self.register_tools_from_string(settings.mcp_tools_string)

    def _init_telemetry(self):
        """Initialize OpenTelemetry for the MCP server."""
        try:
            from telemetry.manager import init_otel

            service_name = os.getenv("OTEL_SERVICE_NAME", "mcp-server")
            init_otel(service_name)
            logger.info("OpenTelemetry initialized for MCP server")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")

    def _log_startup_config(self):
        """Log server configuration on startup for debugging."""
        from telemetry.manager import is_otel_enabled

        logger.info("=" * 60)
        logger.info("MCPServer Starting (Streamable HTTP)")
        logger.info("=" * 60)
        logger.info(f"Host: {self._host}")
        logger.info(f"Port: {self._port}")
        logger.info(f"Endpoint: /mcp")
        logger.info(f"Log Level: {self._log_level}")
        logger.info(f"Access Log: {self._access_log}")
        logger.info(f"Tools Registered: {len(self.tools_registry)}")
        for tool_name in self.tools_registry:
            func = self.tools_registry[tool_name]
            doc = func.__doc__.split("\n")[0] if func.__doc__ else "No description"
            logger.info(f"  - {tool_name}: {doc}")

        # Log OpenTelemetry configuration
        otel_enabled = is_otel_enabled()
        logger.info(f"OpenTelemetry Enabled: {otel_enabled}")
        if otel_enabled:
            logger.info(f"  OTEL_SERVICE_NAME: {os.getenv('OTEL_SERVICE_NAME', 'N/A')}")
            logger.info(
                f"  OTEL_EXPORTER_OTLP_ENDPOINT: {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'N/A')}"
            )
            logger.debug(
                f"  OTEL_RESOURCE_ATTRIBUTES: {os.getenv('OTEL_RESOURCE_ATTRIBUTES', 'N/A')}"
            )

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
        self, transport: Literal["streamable-http", "sse"] = "streamable-http"
    ) -> StarletteWithLifespan:
        """Create FastMCP ASGI app with health probes.

        Args:
            transport: MCP transport type. Default is streamable-http (recommended).
        """
        mcp_app = self.mcp.http_app(transport=transport)

        # Add OTel instrumentation for Starlette if enabled
        if self._otel_enabled:
            try:
                from opentelemetry.instrumentation.starlette import StarletteInstrumentor

                StarletteInstrumentor.instrument_app(mcp_app)
                logger.info("OpenTelemetry Starlette instrumentation enabled")
            except Exception as e:
                logger.warning(f"Failed to enable Starlette instrumentation: {e}")

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

        # Prepend health routes
        mcp_app.routes.insert(0, Route("/health", health))
        mcp_app.routes.insert(1, Route("/ready", ready))

        return mcp_app

    def run(self, transport: Literal["streamable-http", "sse"] = "streamable-http") -> None:
        """Run the MCP server.

        Args:
            transport: MCP transport type. Default is streamable-http (recommended).
        """
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
