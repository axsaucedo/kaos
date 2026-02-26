"""Test helpers for creating AgentServer instances."""

from typing import Any, Optional, List, Dict

from pydantic_ai import Agent as PydanticAgent

from pai_server.server import (
    AgentServer,
)
from pai_server.serverutils import (
    AgentDeps,
    RemoteAgent,
    AgentServerSettings,
    _resolve_model,
    _MockResponseState,
)
from pai_server.tools import DelegationToolset
from pai_server.memory import Memory, LocalMemory, NullMemory


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
    """Create an AgentServer for testing."""
    if memory is None:
        memory = LocalMemory()

    sub_agents_dict: Dict[str, RemoteAgent] = {a.name: a for a in (sub_agents or [])}

    mock_state: Optional[_MockResponseState] = None
    if model is None:
        try:
            model, mock_state = _resolve_model(name)
        except ValueError:
            pass

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

    settings = AgentServerSettings(
        agent_name=name,
        agent_description=description,
        agentic_loop_max_steps=max_steps,
        memory_context_limit=memory_context_limit,
    )

    return AgentServer(
        pydantic_agent=pydantic_agent,
        settings=settings,
        memory=memory,
        mock_state=mock_state,
        sub_agents=sub_agents_dict,
        model=model,
    )
