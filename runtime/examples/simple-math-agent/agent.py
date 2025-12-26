#!/usr/bin/env python3
"""
Simple Math Agent - End-to-end test of agent runtime server.

This example demonstrates:
- Starting the actual runtime/server/server.py as a subprocess
- Configuring it entirely via environment variables
- Making HTTP requests to agent endpoints
- Verifying the agent can reach Ollama and MCP servers

This mimics what happens in Kubernetes:
- Controller creates a Pod with environment variables
- Pod runs: python -m uvicorn runtime.server.server:app
- Other components make HTTP requests to agent endpoints
"""

import os
import asyncio
import subprocess
import time
import logging
import signal
from typing import Optional
from pathlib import Path

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SimpleAgentTest:
    """Test runner for simple math agent using actual server.py."""

    def __init__(self):
        """Initialize test configuration from environment."""
        self.agent_name = os.getenv("AGENT_NAME", "math-agent")
        self.agent_port = int(os.getenv("AGENT_PORT", "8000"))
        self.agent_url = f"http://localhost:{self.agent_port}"
        self.model_api_url = os.getenv("MODEL_API_URL", "http://localhost:11434/v1")
        self.mcp_server_url = os.getenv("MCP_SERVER_MATH_TOOLS_URL", "http://localhost:8001")

        self.server_process = None
        self.server_ready = False

    async def start_server(self) -> bool:
        """Start the agent runtime server as a subprocess."""
        logger.info(f"Starting agent server on port {self.agent_port}...")

        # Find runtime/server directory relative to this script
        # Script is at: runtime/examples/simple-math-agent/agent.py
        # We need: runtime/server/
        script_dir = Path(__file__).parent
        runtime_server_dir = script_dir.parent.parent / "server"

        if not runtime_server_dir.exists():
            logger.error(f"runtime/server directory not found at {runtime_server_dir}")
            return False

        # Prepare environment for server process
        env = os.environ.copy()
        env.update({
            "AGENT_NAME": self.agent_name,
            "AGENT_DESCRIPTION": os.getenv(
                "AGENT_DESCRIPTION",
                "A simple mathematical reasoning agent"
            ),
            "AGENT_INSTRUCTIONS": os.getenv(
                "AGENT_INSTRUCTIONS",
                "You are a helpful mathematical assistant. You have access to a calculator tool."
            ),
            "MODEL_API_URL": self.model_api_url,
            "MODEL_NAME": os.getenv("MODEL_NAME", "smollm2:135m"),
            "MCP_SERVERS": "math-tools",
            "MCP_SERVER_MATH_TOOLS_URL": self.mcp_server_url,
            "SERVER_PORT": str(self.agent_port),
            "AGENT_LOG_LEVEL": os.getenv("AGENT_LOG_LEVEL", "INFO"),
            "PYTHONUNBUFFERED": "1",  # Don't buffer output
        })

        try:
            # Start server using uvicorn
            self.server_process = subprocess.Popen(
                ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", f"--port", str(self.agent_port)],
                cwd=str(runtime_server_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            logger.info("Server process started, waiting for readiness...")
            self.server_ready = await self._wait_for_readiness(timeout=30)

            if self.server_ready:
                logger.info(f"Agent server ready at {self.agent_url}")
                return True
            else:
                logger.error("Server did not become ready in time")
                return False

        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return False

    async def _wait_for_readiness(self, timeout: int = 30) -> bool:
        """Wait for server to be ready."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    response = await client.get(f"{self.agent_url}/ready")
                    if response.status_code == 200:
                        logger.info("Server readiness check passed")
                        return True
            except Exception:
                pass

            await asyncio.sleep(0.5)

        logger.warning(f"Server did not become ready within {timeout}s")
        return False

    async def get_agent_card(self) -> Optional[dict]:
        """Fetch agent card via HTTP (A2A discovery)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.agent_url}/agent/card")
                if response.status_code == 200:
                    card = response.json()
                    logger.info(f"Agent card: {card['name']}")
                    logger.info(f"  Description: {card['description']}")
                    logger.info(f"  Tools: {len(card.get('tools', []))} available")
                    logger.info(f"  Capabilities: {card.get('capabilities', {})}")
                    return card
        except Exception as e:
            logger.error(f"Failed to get agent card: {e}")

        return None

    async def invoke_agent(self, task: str) -> Optional[str]:
        """Invoke agent with a task."""
        try:
            logger.info(f"Invoking agent with task: {task}")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.agent_url}/agent/invoke",
                    json={"task": task},
                )

                if response.status_code == 200:
                    result = response.json()
                    return result.get("result")
                else:
                    logger.error(f"Agent invocation failed: {response.status_code}")
                    logger.error(response.text)
                    return None
        except Exception as e:
            logger.error(f"Error invoking agent: {e}")
            return None

    async def run_tests(self) -> None:
        """Run end-to-end tests."""
        logger.info("="*60)
        logger.info("Simple Math Agent - End-to-End Test")
        logger.info("="*60)

        # Test 1: Agent card discovery
        logger.info("\nTest 1: Agent Card Discovery")
        logger.info("-" * 40)
        card = await self.get_agent_card()
        if not card:
            logger.error("Failed to get agent card")
            return

        # Test 2: Simple math task
        logger.info("\nTest 2: Math Reasoning Task")
        logger.info("-" * 40)
        task = "Calculate: What is 234 + 567 - 89? Show your work step by step."
        result = await self.invoke_agent(task)

        if result:
            logger.info("Agent response:")
            print("\n" + "="*60)
            print(result)
            print("="*60 + "\n")
        else:
            logger.error("Failed to get agent response")

    async def cleanup(self) -> None:
        """Stop the server."""
        if self.server_process:
            logger.info("Stopping agent server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Server didn't stop gracefully, killing...")
                self.server_process.kill()
            logger.info("Agent server stopped")

    async def run(self) -> None:
        """Main test execution."""
        try:
            if not await self.start_server():
                logger.error("Failed to start server")
                return

            await self.run_tests()

        finally:
            await self.cleanup()


async def main():
    """Entry point."""
    test = SimpleAgentTest()
    await test.run()


if __name__ == "__main__":
    asyncio.run(main())
