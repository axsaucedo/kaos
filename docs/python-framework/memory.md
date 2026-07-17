# Memory System

The memory system provides session management and event storage for agents. It tracks conversation history, tool calls, delegations, and provides a bridge between KAOS events and Pydantic AI message types.

## Memory Implementations

| Class | Description | Use Case |
|-------|-------------|----------|
| `LocalMemory` | In-memory storage with limits | Default, single-pod |
| `RemoteMemory` | Central memory-service client (short + long-term tiers) | MemoryStore-bound agents |
| `NullMemory` | No-op implementation | Disabled memory |

## Configuration

### Via Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `true` | Enable/disable all memory operations |
| `MEMORY_CONTEXT_LIMIT` | `6` | Max history events for context window |
| `MEMORY_MAX_SESSIONS` | `1000` | Max sessions (LocalMemory) |
| `MEMORY_MAX_SESSION_EVENTS` | `500` | Max events per session (LocalMemory) |
| `MEMORY_STORE_ENDPOINT` | - | Central memory-service URL (set by the operator when a MemoryStore is bound; selects `RemoteMemory`) |

### Via Agent CRD

```yaml
spec:
  config:
    memory:
      enabled: true
      type: remote            # "remote" (bound MemoryStore) or "local" (pod-local)
      memoryStore: shared-memory
      scope: user             # agent | user | group | session
      tools: all              # all | read | write
      failureMode: soft       # soft | strict
```

See the [Agent CRD](../operator/agent-crd.md#configmemory) and [MemoryStore CRD](../operator/memorystore-crd.md) references for the full memory surface (scopes, tools, client params, storage modes).

### Memory tiers

A `RemoteMemory` agent layers three tiers behind one client:

- **Short-term** — a verbatim window of recent turns replayed for conversational continuity (also the local fallback when the store is degraded).
- **Medium-term** — a rolling summary/digest of evicted turns (`clientParams.rollingSummary`).
- **Long-term** — semantic, cross-session facts extracted into the bound [MemoryStore](../operator/memorystore-crd.md) and recalled by relevance.

`LocalMemory` keeps only the pod-local short-term window.

## Memory-Enabled Gating

When `memory_enabled=False` (or `MEMORY_ENABLED=false`):
- `NullMemory` is used — all operations are no-ops
- No conversation history is maintained between requests
- Memory endpoints return empty results
- Useful for stateless agents or performance-critical paths

## Pydantic AI Bridge

The memory system bridges KAOS `MemoryEvent` objects to Pydantic AI `ModelMessage` types (`ModelRequest` / `ModelResponse`). This enables conversation continuity:

```
Memory Events → _memory_events_to_messages() → Pydantic AI message_history
Pydantic AI run result → _extract_and_persist_events() → Memory Events
```

### Event-to-Message Mapping

| KAOS Event Type | Pydantic AI Type |
|-----------------|-----------------|
| `user_message` | `ModelRequest` with `UserPromptPart` |
| `task_delegation_received` | `ModelRequest` with `UserPromptPart` |
| `agent_response` | `ModelResponse` with `TextPart` |
| `tool_call` | `ModelRequest` with `ToolReturnPart` |
| `tool_result` | `ModelRequest` with `ToolReturnPart` |

### Context Window

The `memory_context_limit` controls how many recent events are included in the Pydantic AI `message_history`. This bounds context size for the LLM.

## MemoryEvent Structure

```python
@dataclass
class MemoryEvent:
    event_id: str
    timestamp: datetime
    event_type: str
    content: Any
    metadata: Dict[str, Any]
```

### Event Types

| Type | Description |
|------|-------------|
| `user_message` | User input |
| `task_delegation_received` | Delegation from parent agent |
| `agent_response` | Final agent output |
| `tool_call` | MCP tool invocation |
| `tool_result` | MCP tool result |
| `delegation_request` | Delegation to sub-agent |
| `delegation_response` | Sub-agent response |
| `error` | Error during processing |

## Session Management

```python
# Create session
session_id = await memory.create_session(app_name="agent", user_id="user123")

# Get or create (idempotent)
session_id = await memory.get_or_create_session(session_id="id", app_name="agent")

# List sessions
sessions = await memory.list_sessions()

# Delete session
await memory.delete_session(session_id)
```

## Event Management

```python
# Create and add event
event = memory.create_event("user_message", "Hello!", metadata={"source": "api"})
await memory.add_event(session_id, event)

# Get events
all_events = await memory.get_session_events(session_id)
filtered = await memory.get_session_events(session_id, event_types=["user_message"])
```

## Memory Endpoints

Always available (not behind a debug flag):

### GET /memory/events

```bash
curl http://localhost:8000/memory/events
curl http://localhost:8000/memory/events?session_id=abc&limit=50
```

### GET /memory/sessions

```bash
curl http://localhost:8000/memory/sessions
```

## RemoteMemory

Central memory-service client used when an agent is bound to a `MemoryStore`. The operator injects `MEMORY_STORE_ENDPOINT` and the runtime routes short- and long-term memory through the service:

```python
from pais.memory import RemoteMemory

memory = RemoteMemory("http://memory-service.namespace:8080")
```

Uses the same API as `LocalMemory`; persistence and cross-session recall are handled by the memory service.

## Cleanup

LocalMemory uses deques for automatic eviction:
- Events evicted when `max_events_per_session` exceeded
- Sessions evicted (oldest 10%) when `max_sessions` exceeded
