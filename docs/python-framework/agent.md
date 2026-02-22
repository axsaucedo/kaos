# Agent Class

The `Agent` class wraps `pydantic_ai.Agent` with KAOS-specific functionality: memory persistence, sub-agent delegation, MCP tools, and telemetry.

## Class Definition

```python
class Agent:
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
        memory_enabled: bool = True,
        model_api_url: Optional[str] = None,
        model_name: Optional[str] = None,
    )
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | str | Yes | - | Unique identifier for the agent |
| `model` | Any | No | - | Pydantic AI model instance (TestModel, FunctionModel, etc.) |
| `instructions` | str | No | "You are a helpful agent" | System prompt |
| `description` | str | No | "Agent" | Human-readable description |
| `memory` | Memory | No | LocalMemory() | Session/event storage |
| `sub_agents` | List[RemoteAgent] | No | [] | Remote agents for delegation |
| `mcp_servers` | list | No | [] | MCPServerStreamableHTTP instances |
| `max_steps` | int | No | 5 | Maximum model calls via `UsageLimits(request_limit=)` |
| `memory_context_limit` | int | No | 6 | Max history events for context |
| `memory_enabled` | bool | No | True | Enable/disable memory operations |
| `model_api_url` | str | No | - | LLM API URL (auto-appends `/v1`) |
| `model_name` | str | No | - | Model name for OpenAI-compatible API |

**Model resolution order:** `model` param → `DEBUG_MOCK_RESPONSES` env var → `model_api_url` + `model_name`.

## Core Methods

### process_message

Process a user message using the Pydantic AI agentic loop.

```python
async def process_message(
    self,
    message: Union[str, List[Dict[str, str]]],
    session_id: Optional[str] = None,
    stream: bool = False,
) -> AsyncIterator[str]
```

- `message`: User message (string) or OpenAI-style message array
- `session_id`: Session ID for conversation continuity
- `stream`: Stream response chunks (True) or yield single response (False)

```python
async for chunk in agent.process_message("Hello!", session_id="my-session"):
    print(chunk, end="")
```

### get_agent_card

Generate an A2A agent card for discovery.

```python
async def get_agent_card(self, base_url: str) -> AgentCard
```

Discovers tools from MCP servers and lists delegation tools as skills.

### close

Close all connections and cleanup.

```python
await agent.close()
```

## Delegation

Sub-agents are registered as `delegate_to_{name}` tool functions on the Pydantic AI agent. The LLM decides when to delegate.

```python
from kaos_server.client import Agent, RemoteAgent

worker = RemoteAgent(name="worker", card_url="http://worker:8000")
coordinator = Agent(
    name="coordinator",
    model_api_url="http://ollama:11434",
    model_name="llama3.2",
    sub_agents=[worker],
    instructions="Delegate tasks to worker when appropriate."
)
```

### Context Forwarding

When delegating, the agent forwards recent conversation context from memory to the sub-agent, capped by `memory_context_limit`.

### Graceful Degradation

- Sub-agents that fail discovery are excluded from tool registration
- Delegation failures return `[Delegation failed: ...]` — the model can retry or use alternatives
- Short discovery timeout (5s) vs longer request timeout (60s)

## Memory Events

The agent automatically logs events to memory:

| Event Type | When Logged |
|------------|-------------|
| `user_message` | Incoming user message |
| `task_delegation_received` | Incoming delegation from another agent |
| `agent_response` | Final response generated |
| `tool_call` | MCP tool invoked |
| `tool_result` | MCP tool result received |
| `delegation_request` | Delegation to sub-agent |
| `delegation_response` | Sub-agent response received |
| `error` | Error during processing |

Both streaming and non-streaming paths persist all events.

## Mock Testing

Use `DEBUG_MOCK_RESPONSES` for deterministic testing:

```bash
# Simple response (no tools)
export DEBUG_MOCK_RESPONSES='["Hello!"]'

# Tool call + final response (2 entries)
export DEBUG_MOCK_RESPONSES='["{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"hi\"}}]}", "Done."]'
```
