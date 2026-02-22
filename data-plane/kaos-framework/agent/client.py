"""
KAOS Agent client — Pydantic AI integration.

Wraps pydantic_ai.Agent with KAOS-specific functionality:
- Env-var driven configuration (operator injects AGENT_NAME, MODEL_API_URL, etc.)
- KAOS memory system (Local/Redis/Null) bridged to Pydantic AI message_history
- Sub-agent delegation as Pydantic AI tool functions
- MCP tool integration via Pydantic AI native MCPServerStreamableHTTP
- DEBUG_MOCK_RESPONSES support via custom FunctionModel
- OpenAI-compatible /v1/chat/completions API surface
"""

import json
import logging
from typing import List, Dict, Any, Optional, AsyncIterator, Union

from agent.tools import (
    execute_delegation,
    format_progress_event,
    DELEGATION_TOOL_PREFIX,
)

from pydantic_ai import Agent as PydanticAgent, RunContext
from pydantic_ai.usage import UsageLimits
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse as PydanticModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai._agent_graph import CallToolsNode
from pydantic_graph import End

from agent.memory import LocalMemory, Memory

# Re-export classes now defined in server.py for backward compatibility
from agent.server import (  # noqa: F401
    AgentDeps,
    AgentCard,
    RemoteAgent,
    _MockResponseState,
    _build_mock_model_function,
    _resolve_model,
    _extract_user_prompt,
)

logger = logging.getLogger(__name__)


class Agent:
    """KAOS Agent — wraps pydantic_ai.Agent with memory, delegation, and telemetry."""

    def __init__(
        self,
        name: str,
        model: Any = None,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: Optional[Memory] = None,
        sub_agents: Optional[List[RemoteAgent]] = None,
        mcp_servers: Optional[list] = None,
        max_steps: int = 5,
        memory_context_limit: int = 6,
        model_api_url: Optional[str] = None,
        model_name: Optional[str] = None,
        tool_call_mode: str = "auto",
        custom_pydantic_agent: Any = None,
    ):
        self.name = name
        self.instructions = instructions
        self.description = description
        self.memory: Memory = memory or LocalMemory()
        self.memory_context_limit = memory_context_limit
        self.max_steps = max_steps
        self.tool_call_mode = tool_call_mode
        self.sub_agents: Dict[str, RemoteAgent] = {
            agent.name: agent for agent in (sub_agents or [])
        }
        self._mcp_servers = mcp_servers or []

        # Resolve the Pydantic AI model
        self._model, self._mock_state = _resolve_model(
            name, model, model_api_url, model_name, tool_call_mode
        )

        # Build the Pydantic AI agent
        if custom_pydantic_agent is not None:
            # Use the pre-built Pydantic AI agent (custom image pattern)
            self._agent = custom_pydantic_agent
            # Override model if mock responses are set
            if self._mock_state is not None:
                self._agent.model = self._model
            elif self._model is not None:
                self._agent.model = self._model
            logger.info(f"Agent {name}: using custom Pydantic AI agent")
        else:
            self._agent = PydanticAgent(
                model=self._model,
                instructions=instructions,
                name=name,
                defer_model_check=True,
                deps_type=AgentDeps,
                toolsets=self._mcp_servers if self._mcp_servers else None,
            )

        # Register delegation tools for sub-agents
        self._register_delegation_tools()

        logger.info(
            f"Agent initialized: {name} (sub_agents={list(self.sub_agents.keys())}, "
            f"mcp_servers={len(self._mcp_servers)}, tool_call_mode={tool_call_mode})"
        )

    def _register_delegation_tools(self):
        """Register delegate_to_{name} tools on the Pydantic AI agent."""
        for sub_agent_name, sub_agent in self.sub_agents.items():
            description = f"Delegate a task to the {sub_agent_name} agent."
            if sub_agent.agent_card:
                description = (
                    f"Delegate a task to the {sub_agent.agent_card.name} agent: "
                    f"{sub_agent.agent_card.description}"
                )
            tool_name = f"{DELEGATION_TOOL_PREFIX}{sub_agent_name}"
            self._register_single_delegation_tool(tool_name, description, sub_agent_name, sub_agent)

    def _register_single_delegation_tool(
        self, tool_name: str, description: str, agent_name: str, sub_agent: "RemoteAgent"
    ):
        """Register a single delegation tool, capturing agent_name/sub_agent via closure scope."""
        memory = self.memory
        ctx_limit = self.memory_context_limit

        @self._agent.tool(name=tool_name, description=description)
        async def _delegate(ctx: RunContext[AgentDeps], task: str) -> str:
            return await execute_delegation(
                agent_name,
                task,
                sub_agent,
                ctx.deps.session_id,
                ctx.deps.memory or memory,
                ctx_limit,
            )

    def _format_progress_event(self, part: ToolCallPart, step: int) -> str:
        """Format a tool call as a JSON progress event for streaming."""
        return format_progress_event(part, step, self.max_steps)

    async def process_message(
        self,
        message: Union[str, List[Dict[str, str]]],
        session_id: Optional[str] = None,
        stream: bool = False,
    ) -> AsyncIterator[str]:
        """Process a message using Pydantic AI agent.

        Yields content chunks (streaming) or single complete response.
        """
        if self._mock_state:
            self._mock_state.reset()

        # Get or create session
        if session_id:
            session_id = await self.memory.get_or_create_session(session_id, "agent", "user")
        else:
            session_id = await self.memory.create_session("agent", "user")

        logger.debug(f"Processing message for session {session_id}, streaming={stream}")

        try:
            # Extract user prompt from message
            user_prompt = self._extract_user_prompt(message)

            # Detect delegation: check if message has task-delegation role
            is_delegation = False
            if isinstance(message, list):
                is_delegation = any(msg.get("role") == "task-delegation" for msg in message)

            # Store incoming message event
            event_type = "task_delegation_received" if is_delegation else "user_message"
            await self.memory.add_event(session_id, event_type, user_prompt)

            # Build message history from memory for context
            message_history = await self._build_message_history(session_id)

            # Pass session_id and memory to tools via deps
            deps = AgentDeps(session_id=session_id, memory=self.memory)

            # Limit model request count to max_steps
            usage_limits = UsageLimits(request_limit=self.max_steps)

            if stream:
                full_response = ""
                step = 0
                # Use iter() for node-by-node control:
                # - Emit progress events for tool calls (frontend reasoning status)
                # - Yield final text after agentic loop completes
                async with self._agent.iter(
                    user_prompt,
                    message_history=message_history,
                    usage_limits=usage_limits,
                    deps=deps,
                ) as run:
                    node = run.next_node
                    while not isinstance(node, End):
                        if isinstance(node, CallToolsNode):
                            has_tools = any(
                                isinstance(p, ToolCallPart) for p in node.model_response.parts
                            )
                            if has_tools:
                                step += 1
                            for part in node.model_response.parts:
                                if isinstance(part, ToolCallPart):
                                    yield self._format_progress_event(part, step)
                        node = await run.next(node)

                if run.result:
                    full_response = str(run.result.output)
                    yield full_response

                await self.memory.add_event(session_id, "agent_response", full_response)
                new_msgs = run.result.new_messages() if run.result else []
                for msg in new_msgs:
                    await self._store_pydantic_message(session_id, msg)
            else:
                result = await self._agent.run(
                    user_prompt,
                    message_history=message_history,
                    usage_limits=usage_limits,
                    deps=deps,
                )
                content = str(result.output) if result.output else ""
                await self.memory.add_event(session_id, "agent_response", content)

                # Store new messages from Pydantic AI into memory
                for msg in result.new_messages():
                    await self._store_pydantic_message(session_id, msg)

                yield content

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            await self.memory.add_event(session_id, "error", str(e))
            yield f"Sorry, I encountered an error: {str(e)}"

    def _extract_user_prompt(self, message: Union[str, List[Dict[str, str]]]) -> str:
        """Extract user prompt from string or message array."""
        if isinstance(message, str):
            return message
        for msg in reversed(message):
            role = msg.get("role", "user")
            if role in ("user", "task-delegation"):
                return msg.get("content", "")
        return ""

    async def _build_message_history(self, session_id: str) -> Optional[list]:
        """Build Pydantic AI message_history from KAOS memory events.

        Returns None if no history, otherwise a list of ModelRequest/ModelResponse.
        Excludes the latest user_message/task_delegation_received (the current prompt)
        and respects memory_context_limit for history size.
        """
        events = await self.memory.get_session_events(session_id)
        if not events or len(events) <= 1:
            return None

        # Exclude latest prompt event (user_message or task_delegation_received)
        prompt_types = ("user_message", "task_delegation_received")
        exclude_idx = None
        for i in range(len(events) - 1, -1, -1):
            if events[i].event_type in prompt_types:
                exclude_idx = i
                break

        replayable = [e for i, e in enumerate(events) if i != exclude_idx]

        # Apply context limit (take most recent N replayable events)
        if self.memory_context_limit and len(replayable) > self.memory_context_limit:
            replayable = replayable[-self.memory_context_limit :]

        history: list = []
        for event in replayable:
            if event.event_type in prompt_types:
                history.append(ModelRequest(parts=[UserPromptPart(content=str(event.content))]))
            elif event.event_type == "agent_response":
                history.append(PydanticModelResponse(parts=[TextPart(content=str(event.content))]))
        return history if history else None

    async def _store_pydantic_message(self, session_id: str, msg: Any) -> None:
        """Store a Pydantic AI message as KAOS memory events."""
        if isinstance(msg, PydanticModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    is_delegation = part.tool_name.startswith("delegate_to_")
                    event_type = "delegation_request" if is_delegation else "tool_call"
                    await self.memory.add_event(
                        session_id,
                        event_type,
                        {"tool": part.tool_name, "arguments": part.args},
                    )
                elif isinstance(part, TextPart):
                    pass  # Final text is stored separately
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    is_delegation = part.tool_name.startswith("delegate_to_")
                    event_type = "delegation_response" if is_delegation else "tool_result"
                    result_content = part.content
                    if isinstance(result_content, (dict, list)):
                        result_value = result_content
                    elif isinstance(result_content, str):
                        try:
                            result_value = json.loads(result_content)
                        except (json.JSONDecodeError, ValueError):
                            result_value = result_content
                    else:
                        result_value = str(result_content)
                    await self.memory.add_event(
                        session_id,
                        event_type,
                        {"tool": part.tool_name, "result": result_value},
                    )

    async def get_agent_card(self, base_url: str) -> AgentCard:
        """Generate agent card for A2A discovery."""
        capabilities = ["message_processing", "task_execution"]
        if self._mcp_servers:
            capabilities.append("tool_execution")
        if self.sub_agents:
            capabilities.append("task_delegation")

        # Discover tools from MCP servers for skills list
        skills: list = []
        for mcp_server in self._mcp_servers:
            try:
                async with mcp_server:
                    tools = await mcp_server.list_tools()
                    for tool in tools:
                        skills.append({"name": tool.name, "description": tool.description or ""})
            except Exception as e:
                logger.warning(f"Failed to list tools from MCP server: {e}")

        # Add native tools defined directly on the Pydantic AI agent
        if hasattr(self._agent, "_function_toolset"):
            toolset = self._agent._function_toolset
            if hasattr(toolset, "tools") and isinstance(toolset.tools, dict):
                for tool_name, tool in toolset.tools.items():
                    if not tool_name.startswith("delegate_to_"):
                        desc = getattr(tool, "description", "") or ""
                        skills.append({"name": tool_name, "description": desc})
                if skills:
                    capabilities.append("tool_execution")

        # Add delegation tools as skills
        for agent_name in self.sub_agents:
            skills.append(
                {
                    "name": f"delegate_to_{agent_name}",
                    "description": f"Delegate task to {agent_name}",
                }
            )

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
            for sub_agent in self.sub_agents.values():
                await sub_agent.close()
            await self.memory.close()
            logger.debug(f"Agent {self.name} closed successfully")
        except Exception as e:
            logger.warning(f"Error closing Agent {self.name}: {e}")
