# Agent Class

The `Agent` class is the core component that processes messages using an LLM with support for tool calling and agent delegation.

## Class Definition

```python
class Agent:
    def __init__(
        self,
        name: str,
        model_api: ModelAPI,
        instructions: str = "You are a helpful agent",
        description: str = "Agent",
        memory: LocalMemory = None,
        mcp_clients: List[MCPClient] = None,
        sub_agents: List[RemoteAgent] = None,
        max_steps: int = 5,
        memory_context_limit: int = 6
    )
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | str | Yes | - | Unique identifier for the agent |
| `model_api` | ModelAPI | Yes | - | LLM client for completions |
| `instructions` | str | No | "You are a helpful agent" | System prompt instructions |
| `description` | str | No | "Agent" | Human-readable description |
| `memory` | LocalMemory | No | New instance | Session/event storage |
| `mcp_clients` | List[MCPClient] | No | [] | Tool clients for MCP servers |
| `sub_agents` | List[RemoteAgent] | No | [] | Remote agents for delegation |
| `max_steps` | int | No | 5 | Maximum agentic loop iterations |
| `memory_context_limit` | int | No | 6 | Max conversation turns in context |

## Agentic Loop Configuration

The agentic loop behavior is controlled by two parameters:

- **`max_steps`**: Maximum reasoning iterations before returning. Prevents infinite loops.
- **`memory_context_limit`**: How many recent conversation turns to include in the context.

```python
# High-complexity tasks with more steps
agent = Agent(
    name="complex-agent",
    model_api=model_api,
    max_steps=10,
    memory_context_limit=10
)

# Simple tasks with fewer steps
agent = Agent(
    name="simple-agent",
    model_api=model_api,
    max_steps=2,
    memory_context_limit=4
)
```

## Core Methods

### process_message

Main method for processing user messages with the agentic loop.

```python
async def process_message(
    self,
    message: str,
    session_id: Optional[str] = None,
    stream: bool = False,
    mock_response: Optional[str] = None
) -> AsyncIterator[str]
```

**Parameters:**
- `message`: User message to process
- `session_id`: Optional session ID (created if not provided)
- `stream`: Whether to stream response word-by-word
- `mock_response`: Mock LLM response for testing

**Returns:** AsyncIterator yielding response chunks

**Example:**
```python
async for chunk in agent.process_message("Hello!", session_id="my-session"):
    print(chunk, end="")
```

### execute_tool

Execute a tool by name with arguments.

```python
async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any
```

**Raises:** `ValueError` if tool not found in any MCP client.

### delegate_to_sub_agent

Delegate a task to a sub-agent with memory logging.

```python
async def delegate_to_sub_agent(
    self,
    agent_name: str,
    task: str,
    session_id: Optional[str] = None
) -> str
```

**Returns:** Response from the sub-agent.

**Raises:** `ValueError` if sub-agent not found.

### get_agent_card

Generate an A2A agent card for discovery.

```python
def get_agent_card(self, base_url: str) -> AgentCard
```

**Returns:** AgentCard with name, description, skills, and capabilities.

## Usage Examples

### Basic Agent

```python
from agent.client import Agent
from modelapi.client import ModelAPI

model_api = ModelAPI(model="smollm2:135m", api_base="http://localhost:8000")
agent = Agent(name="basic", model_api=model_api)

async def main():
    async for response in agent.process_message("What is 2+2?"):
        print(response)
```

### Agent with Tools

```python
from mcptools.client import MCPClient, MCPClientSettings

# Connect to MCP server
mcp_settings = MCPClientSettings(
    mcp_client_host="http://localhost",
    mcp_client_port="8001"
)
mcp_client = MCPClient(mcp_settings)
await mcp_client.discover_tools()

# Create agent with tools
agent = Agent(
    name="with-tools",
    model_api=model_api,
    mcp_clients=[mcp_client],
    instructions="Use the echo tool when asked to echo something."
)
```

### Agent with Sub-Agents

```python
from agent.client import RemoteAgent

# Create remote agent references
worker1 = RemoteAgent(name="worker-1", card_url="http://worker-1:8000")
worker2 = RemoteAgent(name="worker-2", card_url="http://worker-2:8000")

# Create coordinator
coordinator = Agent(
    name="coordinator",
    model_api=model_api,
    sub_agents=[worker1, worker2],
    instructions="Delegate tasks to worker-1 or worker-2 as appropriate."
)
```

### Custom Configuration

```python
# High-complexity tasks with more steps
agent = Agent(
    name="complex-agent",
    model_api=model_api,
    max_steps=10,
    memory_context_limit=10
)

# Simple tasks with fewer steps
agent = Agent(
    name="simple-agent",
    model_api=model_api,
    max_steps=2,
    memory_context_limit=4
)
```

## Memory Integration

The agent automatically logs events to memory:

| Event Type | When Logged |
|------------|-------------|
| `user_message` | When process_message is called |
| `agent_response` | When final response is generated |
| `tool_call` | When a tool is invoked |
| `tool_result` | When tool execution completes |
| `delegation_request` | When delegating to sub-agent |
| `delegation_response` | When receiving sub-agent response |
| `error` | When an error occurs |

Access events via the memory debug endpoints or directly:

```python
events = await agent.memory.get_session_events(session_id)
for event in events:
    print(f"{event.event_type}: {event.content}")
```

## Lifecycle

### Cleanup

Close all connections when done:

```python
await agent.close()
```

This closes:
- ModelAPI HTTP client
- All MCPClient connections
- All RemoteAgent connections

## Multi-Agent System Design

### Sub-Agent Availability and Ordering

When deploying multi-agent systems (e.g., coordinator with workers), agents may start in any order. The framework handles this gracefully:

**Design Principles:**

1. **Graceful Degradation**: If a sub-agent is unavailable during discovery, the coordinator continues to function. The model is informed which agents are unavailable.

2. **Retry on Each Request**: Sub-agent availability is re-checked on each request, allowing recovery when agents become available.

3. **Short Discovery Timeout**: Agent card discovery uses a 5-second timeout (vs 30s for task invocation) since agent cards should respond quickly.

4. **Informative Error Messages**: When delegation fails, the model receives a message like `[Delegation failed: Agent 'worker' is not reachable. Please try an alternative approach.]`

**Example: Coordinator Starts Before Workers**

```python
# Coordinator created with references to workers that don't exist yet
worker1 = RemoteAgent(name="worker-1", card_url="http://worker-1:8000")
worker2 = RemoteAgent(name="worker-2", card_url="http://worker-2:8000")

coordinator = Agent(
    name="coordinator",
    model_api=model_api,
    sub_agents=[worker1, worker2]
)

# First request - workers not available yet
# Model receives: "worker-1: (currently unavailable), worker-2: (currently unavailable)"
# Model can still respond, just can't delegate

# Later, after workers start...
# Next request - workers discovered and available
# Model receives: "worker-1: Worker agent, worker-2: Worker agent"
# Delegation now works
```

### Memory Events for Delegation

| Event Type | Description |
|------------|-------------|
| `delegation_request` | Logged when delegation is attempted |
| `delegation_response` | Logged when sub-agent responds successfully |
| `delegation_error` | Logged when delegation fails (agent unavailable or error) |

### RemoteAgent Properties

```python
remote = RemoteAgent(name="worker", card_url="http://worker:8000")

# Check availability
if remote.available:
    response = await remote.invoke("Do something")
else:
    print(f"Agent unavailable: {remote.last_error}")

# Force re-discovery
await remote.discover(retry=True)
```
