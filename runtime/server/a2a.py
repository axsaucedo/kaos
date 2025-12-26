"""
Agent-to-Agent (A2A) Communication Module.

Handles A2A communication between agents using the well-known
Agent Card HTTP endpoints and ADK A2A protocol.
"""

import os
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)


class A2AClient:
    """Manages A2A communication with peer agents"""

    def __init__(self, self_name: str = "", peer_agents: Optional[Dict[str, str]] = None):
        """Initialize A2A client

        Args:
            self_name: Name of this agent (for identification)
            peer_agents: Optional pre-configured peer agents. If not provided,
                        will load from environment variables.
        """
        self.self_name = self_name
        if peer_agents is not None:
            self.peer_agents = peer_agents
        else:
            self.peer_agents = self._load_peer_config()

    def _load_peer_config(self) -> Dict[str, str]:
        """Load peer agent configuration from environment variables"""
        config = {}

        # Parse PEER_AGENTS env var for agent names
        peer_names = os.getenv("PEER_AGENTS", "").split(",")

        for name in peer_names:
            name = name.strip()
            if not name:
                continue

            # Look for PEER_AGENT_<NAME>_CARD_URL
            url_key = f"PEER_AGENT_{name.upper()}_CARD_URL"
            url = os.getenv(url_key)

            if url:
                config[name] = url
                logger.info(f"Discovered peer agent: {name} -> {url}")
            else:
                logger.warning(f"Peer agent {name} configured but Card URL not found (missing {url_key})")

        return config

    async def get_agent_card(self, peer_name: str) -> Dict[str, Any]:
        """
        Get the Agent Card from a peer agent.

        Agent Card contains metadata about the agent's capabilities,
        tools, and communication endpoints.

        Args:
            peer_name: Name of the peer agent

        Returns:
            Agent Card dictionary
        """
        if peer_name not in self.peer_agents:
            raise ValueError(f"Unknown peer agent: {peer_name}")

        try:
            url = self.peer_agents[peer_name]
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Failed to get agent card for {peer_name}: {e}")
            raise

    async def invoke_peer(
        self,
        peer_name: str,
        request: Dict[str, Any]
    ) -> Any:
        """
        Invoke a peer agent.

        Args:
            peer_name: Name of the peer agent
            request: Request payload

        Returns:
            Response from peer agent
        """
        if peer_name not in self.peer_agents:
            raise ValueError(f"Unknown peer agent: {peer_name}")

        try:
            # First, get the peer's card to find the invoke endpoint
            card = await self.get_agent_card(peer_name)
            endpoint = card.get("endpoint", "")

            if not endpoint:
                raise ValueError(f"No endpoint found in agent card for {peer_name}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{endpoint}/agent/invoke",
                    json=request,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Failed to invoke peer agent {peer_name}: {e}")
            raise

    async def call_peer_tool(
        self,
        peer_name: str,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Any:
        """
        Call a tool on a peer agent.

        Args:
            peer_name: Name of the peer agent
            tool_name: Name of the tool to call
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result
        """
        request = {
            "tool_name": tool_name,
            "tool_input": tool_input
        }
        return await self.invoke_peer(peer_name, request)

    def list_peers(self) -> List[str]:
        """Get list of discovered peer agents"""
        return list(self.peer_agents.keys())


# Global A2A client instance
_a2a_client: Optional[A2AClient] = None


def get_a2a_client() -> A2AClient:
    """Get or create the global A2A client instance"""
    global _a2a_client
    if _a2a_client is None:
        _a2a_client = A2AClient()
    return _a2a_client
