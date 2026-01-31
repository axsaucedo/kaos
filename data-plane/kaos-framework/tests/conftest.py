"""
Pytest configuration and fixtures for agent integration tests.

Provides fixtures for starting/stopping agent server instances and MCP servers.
"""

import os
import subprocess
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import pytest
import httpx

logger = logging.getLogger(__name__)


class AgentServer:
    """Manages an agent server subprocess."""

    def __init__(self, port: int, env_vars: Dict[str, str]):
        """Initialize agent server manager.

        Args:
            port: Port to run server on
            env_vars: Environment variables to pass to server
        """
        self.port = port
        self.env_vars = env_vars
        self.process = None
        self.url = f"http://localhost:{port}"

    def start(self, timeout: int = 10) -> bool:
        logger.info(f"Starting agent server on port {self.port}...")

        # Prepare environment
        env = os.environ.copy()
        env.update(self.env_vars)
        env["PYTHONUNBUFFERED"] = "1"

        # Find repo root directory (where agent/ package is located)
        repo_root = Path(__file__).parent.parent

        try:
            self.process = subprocess.Popen(
                [
                    "python",
                    "-m",
                    "uvicorn",
                    "server.server:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(self.port),
                ],
                cwd=str(repo_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait for server to be ready
            if self._wait_for_readiness(timeout):
                logger.info(f"Agent server ready at {self.url}")
                return True
            else:
                logger.error(f"Server did not become ready within {timeout}s")
                self.stop()
                return False

        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise

    def _wait_for_readiness(self, timeout: int) -> bool:
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                response = httpx.get(f"{self.url}/ready", timeout=1.0)
                if response.status_code == 200:
                    logger.info("Server readiness check passed")
                    return True
            except Exception:
                pass

            time.sleep(0.5)

        return False

    def stop(self):
        if self.process:
            logger.info("Stopping agent server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Server didn't stop gracefully, killing...")
                self.process.kill()
            logger.info("Agent server stopped")

    def get_logs(self) -> str:
        if self.process:
            try:
                stdout, stderr = self.process.communicate(timeout=1)
                return f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            except Exception:
                return "Could not retrieve logs"
        return "No logs available"


class MultiAgentCluster:
    """Manages multiple agent server subprocesses using AgentServer."""

    def __init__(self, agents_config: Dict[str, Dict[str, str]]):
        """Initialize multi-agent cluster manager.

        Args:
            agents_config: Dict of agent_name -> env_vars for each agent
        """
        self.agents_config = agents_config
        self.servers = {}  # agent_name -> AgentServer
        self.urls = {}

    def start(self, timeout: int = 10) -> bool:
        """Start all configured agent servers.

        Args:
            timeout: Maximum seconds to wait for all servers to be ready

        Returns:
            True if all servers started successfully
        """
        logger.info(f"Starting {len(self.agents_config)} agent servers...")

        for agent_name, env_vars in self.agents_config.items():
            port = int(env_vars.get("AGENT_PORT", "8000"))
            self.urls[agent_name] = f"http://localhost:{port}"

            try:
                server = AgentServer(port=port, env_vars=env_vars)
                if not server.start(timeout=timeout):
                    logger.error(f"Failed to start {agent_name}")
                    self.stop()
                    return False
                self.servers[agent_name] = server
                logger.info(f"Started {agent_name} on port {port}")

            except Exception as e:
                logger.error(f"Failed to start agent {agent_name}: {e}")
                self.stop()
                raise

        logger.info("All agent servers ready")
        return True

    def stop(self):
        """Stop all agent servers."""
        for agent_name, server in self.servers.items():
            logger.info(f"Stopping {agent_name}...")
            server.stop()

    def get_url(self, agent_name: str) -> str:
        """Get the URL for an agent."""
        return self.urls[agent_name]


@pytest.fixture
def multi_agent_cluster():
    """Fixture that provides multiple running agent servers."""
    # Configure three agents for multi-agent testing
    # NOTE: Workers are started first (no peer agents), then coordinator with peers
    agents_config = {
        "worker-1": {
            "AGENT_NAME": "worker-1",
            "AGENT_DESCRIPTION": "First worker agent",
            "AGENT_PORT": "8012",
            "AGENT_INSTRUCTIONS": "You are worker agent 1. Respond helpfully to any task.",
            "MODEL_API_URL": os.getenv("MODEL_API_URL", "http://localhost:11434/v1"),
            "MODEL_NAME": os.getenv("MODEL_NAME", "smollm2:135m"),
            "AGENT_LOG_LEVEL": "INFO",
        },
        "worker-2": {
            "AGENT_NAME": "worker-2",
            "AGENT_DESCRIPTION": "Second worker agent",
            "AGENT_PORT": "8013",
            "AGENT_INSTRUCTIONS": "You are worker agent 2. Respond helpfully to any task.",
            "MODEL_API_URL": os.getenv("MODEL_API_URL", "http://localhost:11434/v1"),
            "MODEL_NAME": os.getenv("MODEL_NAME", "smollm2:135m"),
            "AGENT_LOG_LEVEL": "INFO",
        },
        "coordinator": {
            "AGENT_NAME": "coordinator",
            "AGENT_DESCRIPTION": "Coordinator agent",
            "AGENT_PORT": "8011",
            "AGENT_INSTRUCTIONS": "You are the coordinator. You can delegate tasks to worker-1 and worker-2 agents.",
            "MODEL_API_URL": os.getenv("MODEL_API_URL", "http://localhost:11434/v1"),
            "MODEL_NAME": os.getenv("MODEL_NAME", "smollm2:135m"),
            "PEER_AGENTS": "worker-1,worker-2",
            "PEER_AGENT_WORKER_1_CARD_URL": "http://localhost:8012/.well-known/agent",
            "PEER_AGENT_WORKER_2_CARD_URL": "http://localhost:8013/.well-known/agent",
            "AGENT_LOG_LEVEL": "INFO",
        },
    }

    cluster = MultiAgentCluster(agents_config)
    if not cluster.start():
        raise RuntimeError("Failed to start multi-agent cluster")

    yield cluster
    cluster.stop()


class MCPServer:
    """Manages test-mcp-echo-server subprocess."""

    def __init__(self, port: int = 8002):
        """Initialize MCP server manager.

        Args:
            port: Port to run server on
        """
        self.port = port
        self.process = None
        self.url = f"http://localhost:{port}"

    def start(self, timeout: int = 10) -> bool:
        """Start the MCP server as a subprocess.

        Args:
            timeout: Maximum seconds to wait for server to be ready

        Returns:
            True if server started and became ready
        """
        logger.info(f"Starting MCP echo server on port {self.port}...")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["MCP_SERVER_PORT"] = str(self.port)

        try:
            self.process = subprocess.Popen(
                ["test-mcp-echo-server"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait for server to be ready
            if self._wait_for_readiness(timeout):
                logger.info(f"MCP server ready at {self.url}")
                return True
            else:
                logger.error(f"MCP server did not become ready within {timeout}s")
                self.stop()
                return False

        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False

    def _wait_for_readiness(self, timeout: int) -> bool:
        """Wait for MCP server to be ready.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if server is ready
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Try to get tools endpoint which should be available
                response = httpx.get(f"{self.url}/tools", timeout=1.0)
                if response.status_code in (200, 404):
                    # 200 if endpoint exists, 404 if MCP doesn't expose /tools
                    # but server is running
                    logger.info("MCP server responded")
                    return True
            except Exception:
                pass

            time.sleep(0.5)

        return False

    def stop(self):
        """Stop the MCP server."""
        if self.process:
            logger.info("Stopping MCP server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("MCP server didn't stop gracefully, killing...")
                self.process.kill()
            logger.info("MCP server stopped")


@pytest.fixture
def mcp_server():
    """Fixture that provides a started MCP echo server.

    Yields the server instance. Server is stopped after test completes.
    """
    server = MCPServer(port=8002)
    if not server.start():
        raise RuntimeError("Failed to start MCP server")
    yield server
    server.stop()


@pytest.fixture
def agent_server(mcp_server):
    """Fixture that provides a started agent server with MCP configured.

    Depends on mcp_server fixture to ensure MCP is available.
    Yields the server instance. Server is stopped after test completes.
    """
    server = None
    try:
        server = AgentServer(
            port=8001,
            env_vars={
                "AGENT_NAME": "test-agent",
                "AGENT_DESCRIPTION": "Test agent with MCP integration",
                "AGENT_INSTRUCTIONS": "You are a helpful test assistant with access to MCP tools.",
                "MODEL_API_URL": os.getenv("MODEL_API_URL", "http://localhost:11434/v1"),
                "MODEL_NAME": os.getenv("MODEL_NAME", "smollm2:135m"),
                "MCP_SERVERS": "echo_server",
                "MCP_SERVER_ECHO_SERVER_URL": mcp_server.url,
                "AGENT_LOG_LEVEL": "INFO",
            },
        )

        if not server.start():
            raise RuntimeError("Failed to start agent server")

        yield server
    finally:
        if server:
            server.stop()


@pytest.fixture
def agent_server_no_mcp():
    """Fixture that provides an agent server without MCP configuration.

    Useful for testing basic agent functionality without MCP tools.
    """
    server = None
    try:
        server = AgentServer(
            port=8003,
            env_vars={
                "AGENT_NAME": "simple-agent",
                "AGENT_DESCRIPTION": "Simple test agent without MCP",
                "AGENT_INSTRUCTIONS": "You are a helpful test assistant.",
                "MODEL_API_URL": os.getenv("MODEL_API_URL", "http://localhost:11434/v1"),
                "MODEL_NAME": os.getenv("MODEL_NAME", "smollm2:135m"),
                "AGENT_LOG_LEVEL": "INFO",
            },
        )

        if not server.start():
            raise RuntimeError("Failed to start agent server")

        yield server
    finally:
        if server:
            server.stop()
