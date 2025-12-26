#!/usr/bin/env python3
"""
Multi-Agent Coordination Example - Testing A2A communication between agents.

This example demonstrates:
- Starting multiple agent runtime servers in separate processes
- Agent-to-Agent (A2A) communication via HTTP endpoints
- Coordinator delegating tasks to specialized agents
- Dynamic agent discovery via Agent Card endpoints
- Configuration entirely via environment variables

This mimics what happens in Kubernetes:
- Operator creates multiple Agent CRs
- Controller creates Pods running runtime/server/server.py
- Service DNS enables agent discovery
- Agents communicate via /agent/card and /agent/invoke endpoints
"""

import os
import asyncio
import logging
import subprocess
import time
from typing import Optional, List, Dict
from pathlib import Path

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class AgentProcess:
    """Manages a single agent runtime server process."""

    def __init__(self, name: str, port: int, env_vars: Dict[str, str]):
        """Initialize agent process."""
        self.name = name
        self.port = port
        self.env_vars = env_vars
        self.process = None
        self.base_url = f"http://localhost:{port}"

    async def start(self) -> bool:
        """Start the agent runtime server."""
        try:
            logger.info(f"Starting {self.name} agent on port {self.port}...")

            # Find runtime/server directory
            # Script is at: runtime/examples/multi-agent-coordination/orchestrate.py
            # We need: runtime/server/
            script_dir = Path(__file__).parent
            runtime_server_dir = script_dir.parent.parent / "server"

            if not runtime_server_dir.exists():
                logger.error(f"runtime/server not found at {runtime_server_dir}")
                return False

            # Prepare environment for server process
            env = os.environ.copy()
            env.update(self.env_vars)
            env["PYTHONUNBUFFERED"] = "1"

            # Start server using uvicorn
            self.process = subprocess.Popen(
                ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", f"--port", str(self.port)],
                cwd=str(runtime_server_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait for server to be ready
            if await self._wait_for_ready(timeout=30):
                logger.info(f"{self.name} agent started successfully")
                return True
            else:
                logger.error(f"{self.name} agent failed to start")
                return False

        except Exception as e:
            logger.error(f"Failed to start {self.name} agent: {e}")
            return False

    async def _wait_for_ready(self, timeout: int = 30) -> bool:
        """Wait for agent to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    response = await client.get(f"{self.base_url}/ready")
                    if response.status_code == 200:
                        logger.info(f"{self.name} agent readiness check passed")
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)

        logger.warning(f"{self.name} agent did not become ready within {timeout}s")
        return False

    async def stop(self) -> None:
        """Stop the agent process."""
        if self.process:
            logger.info(f"Stopping {self.name} agent...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"{self.name} agent didn't stop gracefully, killing...")
                self.process.kill()
            logger.info(f"{self.name} agent stopped")

    async def get_card(self) -> Optional[Dict]:
        """Get agent card for A2A discovery."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/agent/card")
                if response.status_code == 200:
                    card = response.json()
                    logger.info(f"Retrieved card for {self.name}: {card.get('name')}")
                    return card
        except Exception as e:
            logger.error(f"Failed to get card for {self.name}: {e}")
        return None

    async def invoke(self, task: str) -> Optional[str]:
        """Invoke the agent with a task."""
        try:
            logger.info(f"Invoking {self.name} with task: {task[:50]}...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/agent/invoke",
                    json={"task": task},
                )
                if response.status_code == 200:
                    result = response.json()
                    return result.get("result")
                else:
                    logger.error(f"Invocation failed: {response.status_code}")
                    logger.error(response.text)
        except Exception as e:
            logger.error(f"Failed to invoke {self.name}: {e}")
        return None


class MultiAgentOrchestrator:
    """Orchestrates multiple agent runtime servers."""

    def __init__(self, env_file: str = ".env"):
        """Initialize orchestrator."""
        self.env_file = env_file
        self.agents: Dict[str, AgentProcess] = {}
        self.model_api_url = None
        self.mcp_server_url = None
        self._load_env()

    def _load_env(self) -> None:
        """Load environment configuration from .env file."""
        if os.path.exists(self.env_file):
            logger.info(f"Loading configuration from {self.env_file}")
            with open(self.env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "=" in line:
                            key, value = line.split("=", 1)
                            os.environ[key.strip()] = value.strip()

        self.model_api_url = os.getenv("MODEL_API_URL", "http://localhost:11434/v1")
        self.mcp_server_url = os.getenv("ANALYST_MCP_SERVER_MATH_TOOLS_URL", "http://localhost:8003")

    async def setup_agents(self) -> bool:
        """Setup and start all agents."""
        logger.info("="*60)
        logger.info("Multi-Agent Coordination - Setting up agents")
        logger.info("="*60)

        # Define agent configuration
        agents_config = [
            {
                "name": "coordinator",
                "port": 8000,
                "description": "Orchestrator agent for task coordination",
                "instructions": "You are a coordinator agent. You can delegate tasks to specialized agents.",
                "mcp_servers": "",
                "peer_agents": "researcher,analyst",
            },
            {
                "name": "researcher",
                "port": 8001,
                "description": "Research and information gathering agent",
                "instructions": "You are a researcher agent. You specialize in gathering and analyzing information.",
                "mcp_servers": "",
                "peer_agents": "coordinator",
            },
            {
                "name": "analyst",
                "port": 8002,
                "description": "Analysis and calculation agent with math tools",
                "instructions": "You are an analyst agent. You have math tools available for calculations.",
                "mcp_servers": "math-tools",
                "peer_agents": "coordinator",
            },
        ]

        # Create agents
        for config in agents_config:
            port = config["port"]
            peer_agents_str = config["peer_agents"]

            # Build peer agent endpoints
            peer_endpoints = {}
            for peer_name in peer_agents_str.split(","):
                peer_name = peer_name.strip()
                if peer_name == "researcher":
                    peer_endpoints[f"PEER_AGENT_{peer_name.upper()}_CARD_URL"] = "http://localhost:8001/agent/card"
                elif peer_name == "analyst":
                    peer_endpoints[f"PEER_AGENT_{peer_name.upper()}_CARD_URL"] = "http://localhost:8002/agent/card"
                elif peer_name == "coordinator":
                    peer_endpoints[f"PEER_AGENT_{peer_name.upper()}_CARD_URL"] = "http://localhost:8000/agent/card"

            env = {
                "AGENT_NAME": config["name"],
                "AGENT_DESCRIPTION": config["description"],
                "AGENT_INSTRUCTIONS": config["instructions"],
                "MODEL_API_URL": self.model_api_url,
                "MODEL_NAME": "smollm2:135m",
                "PEER_AGENTS": peer_agents_str,
                "AGENT_LOG_LEVEL": os.getenv("AGENT_LOG_LEVEL", "INFO"),
                **peer_endpoints,
            }

            # Add MCP server config if needed
            if config["mcp_servers"]:
                env["MCP_SERVERS"] = config["mcp_servers"]
                env["MCP_SERVER_MATH_TOOLS_URL"] = self.mcp_server_url

            agent = AgentProcess(config["name"], port, env)
            self.agents[config["name"]] = agent

        # Start all agents
        logger.info("Starting all agents...")
        success = True
        for agent in self.agents.values():
            if not await agent.start():
                success = False

        if success:
            logger.info("All agents started successfully")
            await asyncio.sleep(2)  # Give agents time to discover each other

        return success

    async def run_coordination_test(self) -> None:
        """Run end-to-end coordination tests."""
        logger.info("="*60)
        logger.info("Running coordination tests")
        logger.info("="*60)

        coordinator = self.agents["coordinator"]

        # Test 1: Get agent cards (A2A discovery)
        logger.info("\nTest 1: Agent Card Discovery")
        logger.info("-" * 40)
        for agent_name, agent in self.agents.items():
            card = await agent.get_card()
            if card:
                logger.info(f"  {agent_name}: {card.get('description')}")

        # Test 2: Coordinator delegates math task to analyst
        logger.info("\nTest 2: Coordinator → Analyst (Math Task)")
        logger.info("-" * 40)
        task = "Calculate 456 + 789 - 123. Show the result and explain your reasoning."
        result = await coordinator.invoke(task)
        if result:
            print("\n" + "="*60)
            print(result)
            print("="*60 + "\n")
        else:
            logger.error("Failed to get result from coordinator")

        await asyncio.sleep(2)

        # Test 3: Coordinator delegates to researcher
        logger.info("\nTest 3: Coordinator → Researcher (Analysis Task)")
        logger.info("-" * 40)
        task = "Analyze the capabilities of a multi-agent system where agents can delegate tasks to each other."
        result = await coordinator.invoke(task)
        if result:
            print("\n" + "="*60)
            print(result)
            print("="*60 + "\n")
        else:
            logger.error("Failed to get result from coordinator")

    async def cleanup(self) -> None:
        """Stop all agents."""
        logger.info("Cleaning up agents...")
        for agent in self.agents.values():
            await agent.stop()

    async def run(self) -> None:
        """Run the multi-agent orchestration example."""
        try:
            if not await self.setup_agents():
                logger.error("Failed to setup agents")
                return

            await self.run_coordination_test()

        finally:
            await self.cleanup()


async def main():
    """Main entry point."""
    orchestrator = MultiAgentOrchestrator()
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
