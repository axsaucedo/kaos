# Memory System

The memory system provides session management and event storage for agents. It tracks conversation history, tool calls, delegations, and enables debugging.

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
| `max_sessions` | 1000 | Maximum sessions before cleanup |
| `max_events_per_session` | 500 | Maximum events per session |

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
| `delegation_request` | Sub-agent delegation | `{"agent": "worker", "task": "..."}` |
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

LocalMemory automatically:
- Removes oldest 10% of sessions when `max_sessions` is exceeded
- Keeps 80% of most recent events when `max_events_per_session` is exceeded

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

## Debug Endpoints

When `AGENT_DEBUG_MEMORY_ENDPOINTS=true`, the server exposes:

### GET /memory/events

List all events across all sessions:

```bash
curl http://localhost:8000/memory/events
```

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
