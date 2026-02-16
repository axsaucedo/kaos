# Memory System

The memory system provides session management and event storage for agents. It tracks conversation history, tool calls, delegations, and enables debugging.

## Memory Implementations

KAOS provides two memory implementations:

| Class | Description | Use Case |
|-------|-------------|----------|
| `LocalMemory` | Full in-memory storage with limits | Default, full functionality |
| `NullMemory` | No-op implementation | Disabled memory, stateless agents |

## LocalMemory Class

```python
class LocalMemory:
    def __init__(
        self,
        max_sessions: int = 1000,
        max_events_per_session: int = 500
    )
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_sessions` | 1000 | Maximum sessions before oldest are evicted |
| `max_events_per_session` | 500 | Maximum events per session (uses deque for O(1) eviction) |

## NullMemory Class

No-op implementation for when memory is disabled:

```python
class NullMemory:
    """All operations succeed silently without storing data."""
```

Use when:
- Building stateless agents
- Resource-constrained environments
- Testing without memory overhead

## Configuration

### Via Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `true` | Enable/disable memory |
| `MEMORY_TYPE` | `local` | Memory type (only `local` supported) |
| `MEMORY_CONTEXT_LIMIT` | `6` | Messages for delegation context |
| `MEMORY_MAX_SESSIONS` | `1000` | Max sessions to keep |
| `MEMORY_MAX_SESSION_EVENTS` | `500` | Max events per session |

### Via Agent CRD

```yaml
spec:
  config:
    memory:
      enabled: true
      type: local
      contextLimit: 6
      maxSessions: 1000
      maxSessionEvents: 500
```

## Session Management

### Create Session

```python
session_id = await memory.create_session(
    app_name="agent",
    user_id="user123",
    session_id="custom-id"  # Optional
)
```

### Get or Create Session

Useful when session ID is provided by client:

```python
session_id = await memory.get_or_create_session(
    session_id="provided-id",
    app_name="agent",
    user_id="user"
)
```

### List Sessions

```python
all_sessions = await memory.list_sessions()
user_sessions = await memory.list_sessions(user_id="user123")
```

### Delete Session

```python
deleted = await memory.delete_session(session_id)
```

## Event Management

### MemoryEvent Structure

```python
@dataclass
class MemoryEvent:
    event_id: str           # Unique event identifier
    timestamp: datetime     # When event occurred
    event_type: str         # Category of event
    content: Any            # Event data
    metadata: Dict[str, Any]  # Additional context
```

### Event Types

| Type | Description | Content Example |
|------|-------------|-----------------|
| `user_message` | User input | `"What is 2+2?"` |
| `agent_response` | Final agent output | `"The answer is 4"` |
| `tool_call` | Tool invocation request | `{"tool": "calc", "arguments": {...}}` |
| `tool_result` | Tool execution result | `{"tool": "calc", "result": 4}` |
| `delegation_request` | Sub-agent delegation | `{"tool": "delegate_to_worker", "arguments": {"task": "..."}}` |
| `delegation_response` | Sub-agent response | `{"agent": "worker", "response": "..."}` |
| `error` | Error occurred | `"Connection failed"` |

### Create Event

```python
event = memory.create_event(
    event_type="user_message",
    content="Hello!",
    metadata={"source": "api"}
)
```

### Add Event to Session

```python
success = await memory.add_event(session_id, event)
```

### Get Session Events

```python
# All events
all_events = await memory.get_session_events(session_id)

# Filtered by type
messages = await memory.get_session_events(
    session_id,
    event_types=["user_message", "agent_response"]
)
```

## Conversation Context

Build context string from conversation history:

```python
context = await memory.build_conversation_context(
    session_id,
    max_events=20  # Last 20 messages
)
# Returns:
# "User: Hello!\nAssistant: Hi there!\nUser: How are you?"
```

## Cleanup

### Manual Cleanup

```python
# Remove sessions older than 24 hours
cleaned = await memory.cleanup_old_sessions(max_age_hours=24)
print(f"Cleaned {cleaned} sessions")
```

### Automatic Cleanup

LocalMemory uses a deque (double-ended queue) for event storage:
- Events are automatically evicted when `max_events_per_session` is exceeded
- Session cleanup removes oldest 10% when `max_sessions` is exceeded
- O(1) append and eviction operations

## Statistics

```python
stats = await memory.get_memory_stats()
# Returns:
# {
#     "total_sessions": 42,
#     "total_events": 1337,
#     "avg_events_per_session": 31
# }
```

## Serialization

### Event to Dictionary

```python
event_dict = event.to_dict()
# {
#     "event_id": "event_abc123",
#     "timestamp": "2024-12-31T12:00:00",
#     "event_type": "user_message",
#     "content": "Hello!",
#     "metadata": {}
# }
```

### Event from Dictionary

```python
event = MemoryEvent.from_dict(event_dict)
```

### Session to Dictionary

```python
session = await memory.get_session(session_id)
session_dict = session.to_dict()
```

## Integration with Agent

The Agent class automatically logs events:

```python
# In Agent.process_message()
user_event = self.memory.create_event("user_message", message)
await self.memory.add_event(session_id, user_event)

# After tool call
tool_event = self.memory.create_event("tool_call", tool_call)
await self.memory.add_event(session_id, tool_event)

# After final response
response_event = self.memory.create_event("agent_response", content)
await self.memory.add_event(session_id, response_event)
```

## Memory Endpoints

Memory endpoints are always enabled and available for debugging and the UI:

### GET /memory/events

List events with optional filtering:

```bash
# Get last 100 events (default)
curl http://localhost:8000/memory/events

# Get last 50 events
curl http://localhost:8000/memory/events?limit=50

# Get events for specific session
curl http://localhost:8000/memory/events?session_id=session_abc123

# Combine filters
curl http://localhost:8000/memory/events?session_id=session_abc123&limit=20
```

**Query Parameters:**

| Parameter | Default | Max | Description |
|-----------|---------|-----|-------------|
| `limit` | 100 | 1000 | Maximum events to return |
| `session_id` | - | - | Filter to specific session |

**Response:**

```json
{
  "agent": "my-agent",
  "events": [
    {
      "event_id": "event_abc123",
      "timestamp": "2024-12-31T12:00:00",
      "event_type": "user_message",
      "content": "Hello!"
    }
  ],
  "total": 1
}
```

### GET /memory/sessions

List all session IDs:

```bash
curl http://localhost:8000/memory/sessions
```

```json
{
  "agent": "my-agent",
  "sessions": ["session_abc123", "session_def456"],
  "total": 2
}
```

## Limitations

1. **In-Memory Only**: Data is lost on pod restart
2. **Per-Pod Storage**: No sharing between replicas
3. **No Persistence**: Not backed by external storage

For production use cases requiring persistence, consider:
- Redis-backed memory (future enhancement)
- PostgreSQL storage (future enhancement)
- External session service
