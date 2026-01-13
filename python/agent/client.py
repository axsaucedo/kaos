"""
Agent client implementation for OpenAI-compatible API.

Clean, simple implementation with proper streaming support and tool integration.
Includes agentic loop for tool calling and agent delegation.

Key design principles:
- Agent decides when to delegate/call tools based on model response
- Server only routes requests, never interprets delegation
- DEBUG_MOCK_RESPONSES env var handled by ModelAPI for testing
- RemoteAgent.process_message() uses /v1/chat/completions
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional, AsyncIterator, Union, cast
import httpx
from dataclasses import dataclass

from modelapi.client import ModelAPI
from agent.memory import LocalMemory
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
            "capabilities": self.capabilities,
        }


class RemoteAgent:
    """Remote agent client for A2A protocol with graceful degradation.

    Uses /v1/chat/completions for invocation to pass full context.
    The role "task-delegation" indicates this is a delegated task.
    """

    DISCOVERY_TIMEOUT = 5.0  # Short timeout for agent card discovery
    REQUEST_TIMEOUT = 60.0  # Longer timeout for actual requests

    def __init__(
        self,
        name: str,
        card_url: Optional[str] = None,
        agent_card_url: Optional[str] = None,
    ):
        url = card_url or agent_card_url
        if not url:
            raise ValueError("card_url is required")
        self.name = name
        self.card_url = url.rstrip("/")
        self.agent_card: Optional[AgentCard] = None
        self._active = False
        self._discovery_client = httpx.AsyncClient(timeout=self.DISCOVERY_TIMEOUT)
        self._request_client = httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT)
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
                capabilities=data.get("capabilities", []),
            )
            self._active = True
            logger.info(f"RemoteAgent {self.name} active: {self.agent_card.description}")
            return True
        except Exception as e:
            self._active = False
            logger.warning(f"RemoteAgent {self.name} init failed: {type(e).__name__}: {e}")
            return False

    async def process_message(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[str] = None,
    ) -> str:
        """Process messages via remote agent's /v1/chat/completions.

        Args:
            messages: List of messages providing context. The last message
                     should have role "task-delegation" with the delegated task.
            session_id: Optional session ID for tracking (not currently used by remote).

        Returns:
            The agent's response content.

        Raises:
            RuntimeError: If agent is unavailable or request fails.
        """
        if not self._active:
            if not await self._init():
                raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")

        try:
            response = await self._request_client.post(
                f"{self.card_url}/v1/chat/completions",
                json={"model": self.name, "messages": messages, "stream": False},
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
            await self._request_client.aclose()
        except Exception:
            pass


class Agent:
    """Agent class with agentic loop support for tool calling and delegation."""

    def __init__(
        self,
        name: str,
        model_api: ModelAPI,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: Optional[LocalMemory] = None,
        mcp_clients: Optional[List[MCPClient]] = None,
        sub_agents: Optional[List[RemoteAgent]] = None,
        loop_config: Optional[AgenticLoopConfig] = None,
    ):
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

    async def _build_system_prompt(self) -> str:
        """Build enhanced system prompt with tools and agents info."""
        parts = [self.instructions]

        # Add tools info if available (inline tool description building)
        if self.mcp_clients:
            tools_desc = []
            for mcp_client in self.mcp_clients:
                if not mcp_client._active:
                    await mcp_client._init()
                for tool in mcp_client.get_tools():
                    params_str = json.dumps(tool.parameters, indent=2) if tool.parameters else "{}"
                    tools_desc.append(
                        f"- **{tool.name}**: {tool.description}\n  Parameters: {params_str}"
                    )
            if tools_desc:
                parts.append("\n## Available Tools\n" + "\n".join(tools_desc))
                parts.append(TOOLS_INSTRUCTIONS)

        # Add agents info if available
        if self.sub_agents:
            agents_info = await self._get_agents_description()
            if agents_info:
                parts.append("\n## Available Agents for Delegation\n" + agents_info)
                parts.append(AGENT_INSTRUCTIONS)

        return "\n".join(parts)

    async def _get_agents_description(self) -> str:
        """Get formatted description of all sub-agents, attempting init for inactive ones."""
        available = []
        unavailable = []

        for sub_agent in self.sub_agents.values():
            if not sub_agent._active:
                await sub_agent._init()

            if sub_agent._active and sub_agent.agent_card:
                available.append(
                    f"- **{sub_agent.agent_card.name}**: {sub_agent.agent_card.description}"
                )
            else:
                unavailable.append(f"- **{sub_agent.name}**: (unavailable)")

        parts = available
        if unavailable:
            parts.append("\n**Unavailable agents:**")
            parts.extend(unavailable)
        return "\n".join(parts)

    def _parse_block(self, content: str, block_type: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from a fenced code block (tool_call or delegate)."""
        pattern = rf"```{block_type}\s*\n({{.*?}})\s*\n```"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse {block_type} JSON: {e}")
        return None

    async def process_message(
        self,
        message: Union[str, List[Dict[str, str]]],
        session_id: Optional[str] = None,
        stream: bool = False,
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
        # Get or create session
        if session_id:
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        # Build enhanced system prompt with tools/agents info
        system_prompt = await self._build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        # Handle both string and array input formats
        if isinstance(message, str):
            user_event = self.memory.create_event("user_message", message)
            await self.memory.add_event(session_id, user_event)
            messages.append({"role": "user", "content": message})
        else:
            for msg in message:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    continue  # Skip external system messages

                if role == "task-delegation":
                    delegation_event = self.memory.create_event("task_delegation_received", content)
                    await self.memory.add_event(session_id, delegation_event)
                    messages.append({"role": "user", "content": content})
                else:
                    messages.append({"role": role, "content": content})
                    if role == "user":
                        user_event = self.memory.create_event("user_message", content)
                        await self.memory.add_event(session_id, user_event)

        try:
            # Agentic loop - iterate up to max_steps
            for step in range(self.loop_config.max_steps):
                logger.debug(f"Agentic loop step {step + 1}/{self.loop_config.max_steps}")

                # Get model response (stream=False always returns str)
                content = cast(str, await self.model_api.process_message(messages, stream=False))

                # Check for tool call
                tool_call = self._parse_block(content, "tool_call")
                if tool_call:
                    tool_event = self.memory.create_event("tool_call", tool_call)
                    await self.memory.add_event(session_id, tool_event)

                    try:
                        tool_name = tool_call.get("tool", "")
                        tool_args = tool_call.get("arguments", {})
                        if not tool_name:
                            raise ValueError("Tool name not specified")

                        # Execute tool inline
                        tool_result = None
                        for mcp_client in self.mcp_clients:
                            if tool_name in mcp_client._tools:
                                tool_result = await mcp_client.call_tool(tool_name, tool_args)
                                break
                        if tool_result is None:
                            raise ValueError(f"Tool '{tool_name}' not found")

                        result_event = self.memory.create_event(
                            "tool_result", {"tool": tool_name, "result": tool_result}
                        )
                        await self.memory.add_event(session_id, result_event)

                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": f"Tool result: {json.dumps(tool_result)}"}
                        )
                        continue

                    except Exception as e:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"Tool execution failed: {e}"})
                        continue

                # Check for delegation
                delegation = self._parse_block(content, "delegate")
                if delegation:
                    agent_name = delegation.get("agent", "")
                    task = delegation.get("task", "")

                    if not agent_name or not task:
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": "Invalid delegation: missing 'agent' or 'task'",
                            }
                        )
                        continue

                    try:
                        context_messages = [m for m in messages if m.get("role") != "system"]
                        delegation_result = await self.delegate_to_sub_agent(
                            agent_name, task, context_messages, session_id
                        )

                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": f"Agent response: {delegation_result}"}
                        )
                        continue

                    except ValueError as e:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"Delegation failed: {e}"})
                        continue

                # No tool call or delegation - this is the final response
                response_event = self.memory.create_event("agent_response", content)
                await self.memory.add_event(session_id, response_event)

                if stream:
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
            error_event = self.memory.create_event("error", error_msg)
            await self.memory.add_event(session_id, error_event)
            yield f"Sorry, I encountered an error: {str(e)}"

    async def delegate_to_sub_agent(
        self,
        agent_name: str,
        task: str,
        context_messages: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Delegate a task to a sub-agent with context."""
        sub_agent = self.sub_agents.get(agent_name)
        if not sub_agent:
            raise ValueError(
                f"Sub-agent '{agent_name}' not found. Available: {list(self.sub_agents.keys())}"
            )

        if session_id:
            await self.memory.add_event(
                session_id,
                self.memory.create_event("delegation_request", {"agent": agent_name, "task": task}),
            )

        # Build messages for sub-agent with context
        messages: List[Dict[str, str]] = []
        if context_messages:
            messages.extend(context_messages[-6:])  # Last 6 messages
        messages.append({"role": "task-delegation", "content": task})

        try:
            response = await sub_agent.process_message(messages, session_id=session_id)

            if session_id:
                await self.memory.add_event(
                    session_id,
                    self.memory.create_event(
                        "delegation_response", {"agent": agent_name, "response": response}
                    ),
                )
            return response

        except RuntimeError as e:
            error_msg = str(e)
            logger.warning(f"Delegation to {agent_name} failed: {error_msg}")

            if session_id:
                await self.memory.add_event(
                    session_id,
                    self.memory.create_event(
                        "delegation_error", {"agent": agent_name, "error": error_msg}
                    ),
                )
            return f"[Delegation failed: {error_msg}]"

    def get_agent_card(self, base_url: str) -> AgentCard:
        """Generate agent card for A2A discovery."""
        skills = []
        for mcp_client in self.mcp_clients:
            for tool in mcp_client.get_tools():
                skills.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                )

        capabilities = ["message_processing", "task_execution"]
        if self.mcp_clients:
            capabilities.append("tool_execution")
        if self.sub_agents:
            capabilities.append("task_delegation")

        return AgentCard(
            name=self.name,
            description=self.description,
            url=base_url,
            skills=skills,
            capabilities=capabilities,
        )

    async def close(self):
        """Close all connections and cleanup resources."""
        try:
            if hasattr(self.model_api, "close"):
                await self.model_api.close()
            for mcp_client in self.mcp_clients:
                if hasattr(mcp_client, "close"):
                    await mcp_client.close()
            for sub_agent in self.sub_agents.values():
                await sub_agent.close()
            logger.debug(f"Agent {self.name} closed successfully")
        except Exception as e:
            logger.warning(f"Error closing Agent {self.name}: {e}")
