"""
Agent client implementation following Google ADK patterns.

Clean, simple implementation with proper streaming support and tool integration.
Includes agentic loop for tool calling and agent delegation.
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional, AsyncIterator
import httpx
from dataclasses import dataclass, field

from modelapi.client import ModelAPI
from agent.memory import LocalMemory, MemoryEvent
from mcptools.client import MCPClient

logger = logging.getLogger(__name__)


# System prompt templates for agentic loop
TOOLS_INSTRUCTIONS = """
To use a tool, respond with a JSON block in this exact format:
```tool_call
{"tool": "tool_name", "arguments": {"arg1": "value1"}}
```
Wait for the tool result before providing your final answer.
"""

AGENT_INSTRUCTIONS = """
To delegate a task to another agent, respond with:
```delegate
{"agent": "agent_name", "task": "task description"}
```
Wait for the agent's response before providing your final answer.
"""


@dataclass
class AgenticLoopConfig:
    """Configuration for the agentic reasoning loop."""
    max_steps: int = 5  # Maximum reasoning steps to prevent infinite loops
    enable_tools: bool = True  # Whether to enable tool calling
    enable_delegation: bool = True  # Whether to enable agent delegation


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
    """Simple Agent class following Google ADK patterns with agentic loop support."""

    def __init__(
        self,
        name: str,
        model_api: ModelAPI,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: LocalMemory = None,
        mcp_clients: List[MCPClient] = None,
        sub_agents: List[RemoteAgent] = None,
        loop_config: AgenticLoopConfig = None):

        self.name = name
        self.instructions = instructions
        self.model_api = model_api
        self.memory = memory or LocalMemory()
        self.description = description
        self.mcp_clients = mcp_clients or []
        self.sub_agents = sub_agents or []
        self.loop_config = loop_config or AgenticLoopConfig()

        logger.info(f"Agent initialized: {name}")

    async def initialize(self) -> None:
        """Initialize the agent (no-op, kept for API compatibility)."""
        pass

    async def _build_system_prompt(self) -> str:
        """Build enhanced system prompt with tools and agents info."""
        parts = [self.instructions]
        
        # Add tools info if enabled and available
        if self.loop_config.enable_tools and self.mcp_clients:
            tools_info = await self._get_tools_description()
            if tools_info:
                parts.append("\n## Available Tools\n" + tools_info)
                parts.append(TOOLS_INSTRUCTIONS)
        
        # Add agents info if enabled and available
        if self.loop_config.enable_delegation and self.sub_agents:
            agents_info = await self._get_agents_description()
            if agents_info:
                parts.append("\n## Available Agents for Delegation\n" + agents_info)
                parts.append(AGENT_INSTRUCTIONS)
        
        return "\n".join(parts)

    async def _get_tools_description(self) -> str:
        """Get formatted description of all available tools."""
        tools_desc = []
        for mcp_client in self.mcp_clients:
            for tool in mcp_client.get_tools():
                params_str = json.dumps(tool.parameters, indent=2) if tool.parameters else "{}"
                tools_desc.append(f"- **{tool.name}**: {tool.description}\n  Parameters: {params_str}")
        return "\n".join(tools_desc)

    async def _get_agents_description(self) -> str:
        """Get formatted description of all available sub-agents."""
        agents_desc = []
        for sub_agent in self.sub_agents:
            if not sub_agent.agent_card:
                try:
                    await sub_agent.discover()
                except Exception as e:
                    logger.warning(f"Could not discover sub-agent {sub_agent.name}: {e}")
                    continue
            card = sub_agent.agent_card
            agents_desc.append(f"- **{card.name}**: {card.description}")
        return "\n".join(agents_desc)

    def _parse_tool_call(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract tool call JSON from model response."""
        match = re.search(r'```tool_call\s*\n({.*?})\s*\n```', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse tool call JSON: {e}")
        return None

    def _parse_delegation(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract delegation JSON from model response."""
        match = re.search(r'```delegate\s*\n({.*?})\s*\n```', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse delegation JSON: {e}")
        return None


    async def process_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        stream: bool = False,
        mock_response: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Process a message with agentic loop for tool calling and delegation.

        Args:
            message: User message to process
            session_id: Optional session ID (created if not provided)
            stream: Whether to stream the response
            mock_response: Mock response for testing (bypasses LLM call)

        Yields:
            Content chunks (streaming) or single complete response (non-streaming)
        """
        # Get or create session - handles both provided and new session IDs
        if session_id:
            # Use provided session ID, creating session if it doesn't exist
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            # Create new session with auto-generated ID
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        # Log user message
        user_event = self.memory.create_event("user_message", message)
        await self.memory.add_event(session_id, user_event)

        # Build enhanced system prompt with tools/agents info
        system_prompt = await self._build_system_prompt()
        
        # Initialize conversation
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": message})

        try:
            # Agentic loop - iterate up to max_steps
            for step in range(self.loop_config.max_steps):
                logger.debug(f"Agentic loop step {step + 1}/{self.loop_config.max_steps}")
                
                # Get model response
                if mock_response and step == 0:
                    # Use mock response for first step (for testing)
                    content = mock_response
                else:
                    response = await self.model_api.complete(messages)
                    content = response["choices"][0]["message"]["content"]
                
                # Check for tool call
                if self.loop_config.enable_tools:
                    tool_call = self._parse_tool_call(content)
                    if tool_call:
                        # Log tool call
                        tool_event = self.memory.create_event("tool_call", tool_call)
                        await self.memory.add_event(session_id, tool_event)
                        
                        # Execute tool
                        try:
                            tool_name = tool_call.get("tool")
                            tool_args = tool_call.get("arguments", {})
                            tool_result = await self.execute_tool(tool_name, tool_args)
                            
                            # Log tool result
                            result_event = self.memory.create_event("tool_result", {
                                "tool": tool_name, "result": tool_result
                            })
                            await self.memory.add_event(session_id, result_event)
                            
                            # Add to conversation and continue loop
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": f"Tool result: {json.dumps(tool_result)}"})
                            continue
                            
                        except Exception as e:
                            error_msg = f"Tool execution failed: {str(e)}"
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": error_msg})
                            continue
                
                # Check for delegation
                if self.loop_config.enable_delegation:
                    delegation = self._parse_delegation(content)
                    if delegation:
                        agent_name = delegation.get("agent")
                        task = delegation.get("task")
                        
                        try:
                            # Delegate to sub-agent (this logs events internally)
                            delegation_result = await self.delegate_to_sub_agent(
                                agent_name, task, session_id
                            )
                            
                            # Add to conversation and continue loop
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": f"Agent response: {delegation_result}"})
                            continue
                            
                        except ValueError as e:
                            error_msg = f"Delegation failed: {str(e)}"
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": error_msg})
                            continue
                
                # No tool call or delegation - this is the final response
                response_event = self.memory.create_event("agent_response", content)
                await self.memory.add_event(session_id, response_event)
                
                if stream:
                    # For streaming, yield word by word (simplified)
                    for word in content.split():
                        yield word + " "
                else:
                    yield content
                return
            
            # Max steps reached
            max_steps_msg = f"Reached maximum reasoning steps ({self.loop_config.max_steps})"
            logger.warning(max_steps_msg)
            yield max_steps_msg

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
        # TODO: Update self.sub_agents to be a dict instead as this woudl allow more efficient
        #    access across these and easier ability to access available sub_agents
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

