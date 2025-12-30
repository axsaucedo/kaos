"""
Agent client implementation following Google ADK patterns.

Clean, simple implementation with proper streaming support and tool integration.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncIterator
import httpx
from dataclasses import dataclass

from modelapi.client import ModelAPI
from agent.memory import LocalMemory, MemoryEvent
from mcptools.client import MCPClient

logger = logging.getLogger(__name__)


@dataclass
class AgentCard:
    """Agent discovery card for A2A protocol."""
    name: str
    description: str
    url: str
    skills: List[Dict[str, Any]]
    capabilities: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "skills": self.skills,
            "capabilities": self.capabilities
        }


class RemoteAgent:

    def __init__(self, name: str, card_url: str = None, agent_card_url: str = None):
        # Handle legacy parameter
        url = card_url or agent_card_url
        if not url:
            raise ValueError("card_url (or agent_card_url) is required")
        self.name = name
        self.card_url = url.rstrip('/')
        self.agent_card: Optional[AgentCard] = None

        # HTTP client with reasonable timeout
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"RemoteAgent initialized: {name} -> {url}")

    async def discover(self) -> AgentCard:
        try:
            response = await self.client.get(f"{self.card_url}/.well-known/agent")
            response.raise_for_status()

            card_data = response.json()
            self.agent_card = AgentCard(
                name=card_data.get("name", self.name),
                description=card_data.get("description", ""),
                url=self.card_url,  # Use the provided card_url, not the one from the response (which may be localhost)
                skills=card_data.get("skills", []),
                capabilities=card_data.get("capabilities", [])
            )

            logger.info(f"Discovered remote agent: {self.name} at {self.card_url} - {self.agent_card.description}")
            return self.agent_card

        except httpx.HTTPError as e:
            logger.error(f"Failed to discover agent {self.name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error discovering agent {self.name}: {e}")
            raise

    async def invoke(self, task: str) -> str:
        if not self.agent_card:
            await self.discover()

        try:
            response = await self.client.post(
                f"{self.agent_card.url}/agent/invoke",
                json={"task": task}
            )
            response.raise_for_status()

            result = response.json()
            response_text = result.get("response", str(result))

            logger.debug(f"Remote agent {self.name} completed task")
            return response_text

        except httpx.HTTPError as e:
            logger.error(f"Failed to invoke agent {self.name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error invoking agent {self.name}: {e}")
            raise

    async def close(self):
        """Close HTTP client and cleanup resources."""
        try:
            await self.client.aclose()
            logger.debug(f"RemoteAgent closed: {self.name}")
        except Exception as e:
            logger.warning(f"Error closing RemoteAgent {self.name}: {e}")


class Agent:
    """Simple Agent class following Google ADK patterns."""

    def __init__(
        self,
        name: str,
        model_api: ModelAPI,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: LocalMemory = LocalMemory(),
        mcp_clients: List[MCPClient] = [],
        sub_agents: List[RemoteAgent] = []):

        self.name = name
        self.instructions = instructions
        self.model_api = model_api
        self.memory = memory
        self.description = description
        self.mcp_clients = mcp_clients
        self.sub_agents = sub_agents

        logger.info(f"Agent initialized: {name}")

    async def initialize(self) -> None:
        """Initialize the agent (no-op, kept for API compatibility)."""
        pass


    async def process_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        stream: bool = False
    ) -> AsyncIterator[str]:
        """Process a message and return response (streaming or non-streaming).

        Args:
            message: User message to process
            session_id: Optional session ID (created if not provided)
            stream: Whether to stream the response

        Yields:
            Content chunks (streaming) or single complete response (non-streaming)
        """
        # Create session if needed
        if not session_id:
            session_id = await self.memory.create_session("agent", "user", session_id)

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        # Log user message
        user_event = self.memory.create_event("user_message", message)
        await self.memory.add_event(session_id, user_event)

        # TODO: Make the adding of context optional and disabled by default such that
        #    it is enabled with a config variable (as part of context) such that it allows
        #    for reduction of "magic" bastractions that happen witout explicit
        # TODO: k8s - ensure that kubernetes operator also extends the CRD to enabel context 
        #    via CRD parameters such as context: enabled / context: max_events which would
        #    translate into a set of env variables that should be accepted
        # TODO: Ensure that the context built is on the same format as the openai compliant
        #    Messages such as role system/user/agent as right now it's not compatible and would
        #   be best to have them lie this
        context = await self.memory.build_conversation_context(session_id)

        messages = [{"role": "system", "content": self.instructions}]
        if context:
            messages.append({"role": "user", "content": context})
        messages.append({"role": "user", "content": message})

        try:
            if stream:
                # Streaming response
                response_chunks = []
                async for chunk in self.model_api.stream(messages):
                    response_chunks.append(chunk)
                    yield chunk

                # Log complete response
                complete_response = "".join(response_chunks)
                response_event = self.memory.create_event("agent_response", complete_response)
                await self.memory.add_event(session_id, response_event)

            else:
                # Non-streaming response
                response = await self.model_api.complete(messages)
                content = response["choices"][0]["message"]["content"]

                # Log response
                response_event = self.memory.create_event("agent_response", content)
                await self.memory.add_event(session_id, response_event)

                yield content

        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            logger.error(error_msg)

            # Log error event
            error_event = self.memory.create_event("error", error_msg)
            await self.memory.add_event(session_id, error_event)

            yield f"Sorry, I encountered an error: {str(e)}"

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        for mcp_client in self.mcp_clients:
            if tool_name in mcp_client._tools:
                return await mcp_client.call_tool(tool_name, args)
        raise ValueError(f"Tool '{tool_name}' not found in any tool client")

    async def delegate_to_sub_agent(self, agent_name: str, task: str, session_id: Optional[str] = None) -> str:
        """Delegate a task to a sub-agent with memory logging.
        
        Args:
            agent_name: Name of the sub-agent to delegate to
            task: Task to delegate
            session_id: Optional session ID for memory logging
            
        Returns:
            Response from the sub-agent
        """
        for sub_agent in self.sub_agents:
            if sub_agent.name == agent_name:
                # Log delegation request
                if session_id:
                    delegation_event = self.memory.create_event(
                        "delegation_request",
                        {"agent": agent_name, "task": task}
                    )
                    await self.memory.add_event(session_id, delegation_event)
                
                logger.info(f"Delegating to sub-agent {agent_name}: {task[:50]}...")
                
                # Invoke sub-agent
                response = await sub_agent.invoke(task)
                
                # Log delegation response
                if session_id:
                    response_event = self.memory.create_event(
                        "delegation_response",
                        {"agent": agent_name, "response": response}
                    )
                    await self.memory.add_event(session_id, response_event)
                
                logger.info(f"Received response from sub-agent {agent_name}")
                return response

        raise ValueError(f"Sub-agent '{agent_name}' not found")

    def get_agent_card(self, base_url: str) -> AgentCard:
        # Collect available tools
        skills = []
        for mcp_client in self.mcp_clients:
            tools = mcp_client.get_tools()
            for tool in tools:
                skills.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                })

        # Collect sub-agent capabilities
        capabilities = ["message_processing", "task_execution"]  # Basic capabilities
        if self.mcp_clients:
            capabilities.append("tool_execution")
        if self.sub_agents:
            capabilities.append("task_delegation")

        return AgentCard(
            name=self.name,
            description=self.description,  # Use the actual description
            url=base_url,
            skills=skills,
            capabilities=capabilities
        )

    async def close(self):
        """Close all connections and cleanup resources."""
        try:
            # Close model client
            if hasattr(self.model_api, 'close'):
                await self.model_api.close()

            # Close tool clients
            for mcp_client in self.mcp_clients:
                if hasattr(mcp_client, 'close'):
                    await mcp_client.close()

            # Close sub-agents
            for sub_agent in self.sub_agents:
                await sub_agent.close()

            logger.debug(f"Agent {self.name} closed successfully")

        except Exception as e:
            logger.warning(f"Error closing Agent {self.name}: {e}")

