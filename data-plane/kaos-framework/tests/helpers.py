"""Test helpers for creating AgentServer instances."""

from typing import Any, Optional, List, Dict

from pydantic_ai import Agent as PydanticAgent

from agent.server import (
    AgentServer,
)
from agent.config import (
    AgentDeps,
    RemoteAgent,
    _resolve_model,
    _MockResponseState,
)
from agent.tools import DelegationToolset
from agent.memory import Memory, LocalMemory, NullMemory


def make_test_server(
    name: str = "test-agent",
    model: Any = None,
    instructions: str = "You are a helpful agent",
    description: str = "Agent",
    memory: Optional[Memory] = None,
    sub_agents: Optional[List[RemoteAgent]] = None,
    max_steps: int = 5,
    memory_context_limit: int = 6,
) -> AgentServer:
    """Create an AgentServer for testing.

    If no model is provided, attempts to resolve from DEBUG_MOCK_RESPONSES env var.
    Tools can be registered via server._agent.tool_plain(...).
    Messages processed via server._process_message(...).
    """
    if memory is None:
        memory = LocalMemory()

    sub_agents_dict: Dict[str, RemoteAgent] = {a.name: a for a in (sub_agents or [])}

    # Resolve model (handles DEBUG_MOCK_RESPONSES env var)
    mock_state: Optional[_MockResponseState] = None
    if model is None:
        try:
            model, mock_state = _resolve_model(name, None, None, None, "auto")
        except ValueError:
            pass

    # Build toolsets
    toolsets: list = []
    if sub_agents_dict:
        toolsets.append(DelegationToolset(sub_agents_dict, memory_context_limit))

    pydantic_agent: PydanticAgent[AgentDeps] = PydanticAgent(
        model=model,
        instructions=instructions,
        name=name,
        defer_model_check=True,
        deps_type=AgentDeps,
        toolsets=toolsets if toolsets else None,
    )

    return AgentServer(
        pydantic_agent=pydantic_agent,
        name=name,
        description=description,
        memory=memory,
        max_steps=max_steps,
        memory_context_limit=memory_context_limit,
        mock_state=mock_state,
        sub_agents=sub_agents_dict,
        model=model,
    )
