"""
Agent client implementation following Google ADK patterns.

Clean, simple implementation with proper streaming support and tool integration.
Includes agentic loop for tool calling and agent delegation.

Key design principles:
- Agent decides when to delegate/call tools based on model response
- Server only routes requests, never interprets delegation
- DEBUG_MOCK_RESPONSES env var for testing (array of responses for agentic loop)
- RemoteAgent.invoke() uses /v1/chat/completions with full context
"""

import os
import json
import re
import logging
from typing import List, Dict, Any, Optional, AsyncIterator, Union
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


def get_mock_responses() -> Optional[List[str]]:
    """Get mock responses from DEBUG_MOCK_RESPONSES env var.
    
    Format: JSON array of strings, e.g.:
    ["first response", "second response"]
    
    Supports multiline responses in the JSON array.
    """
    mock_env = os.environ.get("DEBUG_MOCK_RESPONSES")
    if not mock_env:
        return None
    try:
        responses = json.loads(mock_env)
        if isinstance(responses, list):
            return responses
        # Single string - wrap in list
        return [responses]
    except json.JSONDecodeError:
        # Treat as single plain text response
        return [mock_env]


@dataclass
class AgenticLoopConfig:
    """Configuration for the agentic reasoning loop."""
    max_steps: int = 5  # Maximum reasoning steps to prevent infinite loops


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
    """Remote agent client for A2A protocol with graceful degradation.
    
    Uses /v1/chat/completions for invocation to pass full context.
    The role "task-delegation" indicates this is a delegated task.
    """

    DISCOVERY_TIMEOUT = 5.0  # Short timeout for agent card discovery
    INVOKE_TIMEOUT = 60.0    # Longer timeout for actual invocations

    def __init__(self, name: str, card_url: str = None, agent_card_url: str = None):
        url = card_url or agent_card_url
        if not url:
            raise ValueError("card_url is required")
        self.name = name
        self.card_url = url.rstrip('/')
        self.agent_card: Optional[AgentCard] = None
        self._active = False
        self._discovery_client = httpx.AsyncClient(timeout=self.DISCOVERY_TIMEOUT)
        self._invoke_client = httpx.AsyncClient(timeout=self.INVOKE_TIMEOUT)
        logger.info(f"RemoteAgent initialized: {name} -> {url}")

    async def _init(self) -> bool:
        """Fetch agent card and activate. Returns True if successful."""
        try:
            response = await self._discovery_client.get(f"{self.card_url}/.well-known/agent")
            response.raise_for_status()
            data = response.json()
            self.agent_card = AgentCard(
                name=data.get("name", self.name),
                description=data.get("description", ""),
                url=self.card_url,
                skills=data.get("skills", []),
                capabilities=data.get("capabilities", [])
            )
            self._active = True
            logger.info(f"RemoteAgent {self.name} active: {self.agent_card.description}")
            return True
        except Exception as e:
            self._active = False
            logger.warning(f"RemoteAgent {self.name} init failed: {type(e).__name__}: {e}")
            return False

    async def invoke(self, messages: List[Dict[str, str]]) -> str:
        """Invoke agent with full message context via /v1/chat/completions.
        
        Args:
            messages: List of messages providing context. The last message 
                     should have role "task-delegation" with the delegated task.
                     
        Returns:
            The agent's response content.
            
        Raises:
            RuntimeError: If agent is unavailable or invocation fails.
        """
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")

        try:
            response = await self._invoke_client.post(
                f"{self.card_url}/v1/chat/completions",
                json={
                    "model": self.name,
                    "messages": messages,
                    "stream": False
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            self._active = False
            raise RuntimeError(f"Agent {self.name}: {type(e).__name__}: {e}")

    async def close(self):
        """Close HTTP clients."""
        try:
            await self._discovery_client.aclose()
            await self._invoke_client.aclose()
        except Exception:
            pass


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
        self.sub_agents: Dict[str, RemoteAgent] = {
            agent.name: agent for agent in (sub_agents or [])
        }
        self.loop_config = loop_config or AgenticLoopConfig()

        logger.info(f"Agent initialized: {name}")

    async def initialize(self) -> None:
        """Initialize the agent (no-op, kept for API compatibility)."""
        pass

    async def _build_system_prompt(self) -> str:
        """Build enhanced system prompt with tools and agents info."""
        parts = [self.instructions]
        
        # Add tools info if available
        if self.mcp_clients:
            tools_info = await self._get_tools_description()
            if tools_info:
                parts.append("\n## Available Tools\n" + tools_info)
                parts.append(TOOLS_INSTRUCTIONS)
        
        # Add agents info if available
        if self.sub_agents:
            agents_info = await self._get_agents_description()
            if agents_info:
                parts.append("\n## Available Agents for Delegation\n" + agents_info)
                parts.append(AGENT_INSTRUCTIONS)
        
        return "\n".join(parts)

    async def _get_tools_description(self) -> str:
        """Get formatted description of all available tools, initing inactive clients."""
        tools_desc = []
        for mcp_client in self.mcp_clients:
            if not mcp_client._active:
                await mcp_client._init()
            for tool in mcp_client.get_tools():
                params_str = json.dumps(tool.parameters, indent=2) if tool.parameters else "{}"
                tools_desc.append(f"- **{tool.name}**: {tool.description}\n  Parameters: {params_str}")
        return "\n".join(tools_desc)

    async def _get_agents_description(self) -> str:
        """Get formatted description of all sub-agents, attempting init for inactive ones."""
        available = []
        unavailable = []
        
        for sub_agent in self.sub_agents.values():
            if not sub_agent._active:
                await sub_agent._init()
            
            if sub_agent._active and sub_agent.agent_card:
                available.append(f"- **{sub_agent.agent_card.name}**: {sub_agent.agent_card.description}")
            else:
                unavailable.append(f"- **{sub_agent.name}**: (unavailable)")
        
        parts = available
        if unavailable:
            parts.append("\n**Unavailable agents:**")
            parts.extend(unavailable)
        return "\n".join(parts)

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
        message: Union[str, List[Dict[str, str]]],
        session_id: Optional[str] = None,
        stream: bool = False
    ) -> AsyncIterator[str]:
        """Process a message with agentic loop for tool calling and delegation.

        Args:
            message: User message to process - can be a string or OpenAI-style message array
            session_id: Optional session ID (created if not provided)
            stream: Whether to stream the response

        Yields:
            Content chunks (streaming) or single complete response (non-streaming)
            
        Note:
            For testing, set DEBUG_MOCK_RESPONSES env var to a JSON array of responses
            that will be used instead of calling the model API.
        """
        # Get or create session - handles both provided and new session IDs
        if session_id:
            # Use provided session ID, creating session if it doesn't exist
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            # Create new session with auto-generated ID
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        # Build enhanced system prompt with tools/agents info
        system_prompt = await self._build_system_prompt()
        
        # Initialize conversation with system prompt
        messages = [{"role": "system", "content": system_prompt}]
        
        # Handle both string and array input formats
        if isinstance(message, str):
            # Simple string message - log and append
            user_event = self.memory.create_event("user_message", message)
            await self.memory.add_event(session_id, user_event)
            messages.append({"role": "user", "content": message})
        else:
            # OpenAI-style message array - append all messages (except system, we use ours)
            for msg in message:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    # Skip external system messages, we use our own enhanced one
                    continue
                    
                # Handle task-delegation role: log it specially but convert to user for model
                if role == "task-delegation":
                    # Log as delegation task received
                    delegation_event = self.memory.create_event("task_delegation_received", content)
                    await self.memory.add_event(session_id, delegation_event)
                    # Convert to user role for the model
                    messages.append({"role": "user", "content": content})
                else:
                    messages.append({"role": role, "content": content})
                    # Log user messages to memory
                    if role == "user":
                        user_event = self.memory.create_event("user_message", content)
                        await self.memory.add_event(session_id, user_event)

        # Get mock responses if configured
        mock_responses = get_mock_responses()
        mock_step = 0

        try:
            # Agentic loop - iterate up to max_steps
            for step in range(self.loop_config.max_steps):
                logger.debug(f"Agentic loop step {step + 1}/{self.loop_config.max_steps}")
                
                # Get model response (or mock if configured)
                if mock_responses and mock_step < len(mock_responses):
                    content = mock_responses[mock_step]
                    mock_step += 1
                    logger.debug(f"Using mock response {mock_step}: {content[:50]}...")
                else:
                    response = await self.model_api.complete(messages)
                    content = response["choices"][0]["message"]["content"]
                
                # Check for tool call
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
                delegation = self._parse_delegation(content)
                if delegation:
                    agent_name = delegation.get("agent")
                    task = delegation.get("task")
                    
                    try:
                        # Build context messages for sub-agent (exclude system prompt)
                        context_messages = [m for m in messages if m.get("role") != "system"]
                        
                        # Delegate to sub-agent with context
                        delegation_result = await self.delegate_to_sub_agent(
                            agent_name, task, context_messages, session_id
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

    async def delegate_to_sub_agent(
        self, 
        agent_name: str, 
        task: str, 
        context_messages: List[Dict[str, str]] = None,
        session_id: Optional[str] = None
    ) -> str:
        """Delegate a task to a sub-agent with context.
        
        Args:
            agent_name: Name of the sub-agent to delegate to
            task: The task description to delegate
            context_messages: Previous conversation context (excluding system prompt)
            session_id: Optional session ID for memory tracking
            
        Returns:
            The sub-agent's response
        """
        sub_agent = self.sub_agents.get(agent_name)
        if not sub_agent:
            raise ValueError(f"Sub-agent '{agent_name}' not found. Available: {list(self.sub_agents.keys())}")
        
        # Log delegation request
        if session_id:
            await self.memory.add_event(session_id, self.memory.create_event(
                "delegation_request", {"agent": agent_name, "task": task}
            ))
        
        # Build messages for the sub-agent
        # Include context (if any) plus the delegated task with special role
        messages = []
        if context_messages:
            # Include relevant context but limit to avoid too much history
            messages.extend(context_messages[-6:])  # Last 6 messages of context
        
        # Add the delegated task with task-delegation role
        messages.append({"role": "task-delegation", "content": task})
        
        try:
            response = await sub_agent.invoke(messages)
            
            if session_id:
                await self.memory.add_event(session_id, self.memory.create_event(
                    "delegation_response", {"agent": agent_name, "response": response}
                ))
            return response
            
        except RuntimeError as e:
            error_msg = str(e)
            logger.warning(f"Delegation to {agent_name} failed: {error_msg}")
            
            if session_id:
                await self.memory.add_event(session_id, self.memory.create_event(
                    "delegation_error", {"agent": agent_name, "error": error_msg}
                ))
            return f"[Delegation failed: {error_msg}]"

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
            for sub_agent in self.sub_agents.values():
                await sub_agent.close()

            logger.debug(f"Agent {self.name} closed successfully")

        except Exception as e:
            logger.warning(f"Error closing Agent {self.name}: {e}")

