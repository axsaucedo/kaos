---
applyTo: "data-plane/kaos-framework/**"
---

# Python Agent Framework Instructions

## Quick Reference
```bash
cd data-plane/kaos-framework
source .venv/bin/activate
python -m pytest tests/ -v      # Run all tests
make lint                       # Run linting (black + ty check)
make format                     # Auto-format code
```

## Project Structure
- `agent/client.py`: Agent, RemoteAgent, AgentCard classes with two-phase agentic loop
- `agent/server.py`: AgentServer with A2A endpoints
- `agent/memory.py`: LocalMemory for session/event management
- `agent/telemetry/`: OpenTelemetry instrumentation (tracing, metrics)
- `mcptools/`: MCP (Model Context Protocol) tools
- `modelapi/`: Model API client for OpenAI-compatible servers

## Key Environment Variables
| Variable | Description |
|----------|-------------|
| `AGENT_NAME` | Agent name (required) |
| `MODEL_API_URL` | LLM API base URL (required) |
| `MODEL_NAME` | Model name (required) |
| `AGENT_SUB_AGENTS` | Direct format: `"name:url,name:url"` |
| `DEBUG_MOCK_RESPONSES` | JSON array of mock responses (tool_calls JSON or plain text) |
| `OTEL_ENABLED` | Enable OpenTelemetry instrumentation |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP exporter endpoint |

## Agentic Loop (Two-Phase)

The agent auto-detects native tool calling support using `litellm.supports_function_calling(model)`:
- **Native**: Models with function calling use the OpenAI `tools` API parameter
- **String fallback**: Models without support get tool descriptions in the system prompt and output `{"tool": "name", "arguments": {...}}` in content

Both modes use the same unified format — delegation uses `delegate_to_` prefix: `{"tool": "delegate_to_worker", "arguments": {"task": "..."}}`.

### Phase 1 (Tool Calling)
1. Non-streaming model calls (with `tools` param for native, or tools in system prompt for string)
2. Tool calls extracted from `response.tool_calls` first (both modes), then content JSON parsing as fallback
3. Both MCP tools and sub-agent delegation use identical `{"tool": "name", "arguments": {...}}` format
4. Loops until no tool calls detected in response

### Phase 2 (Final Response)
- Streaming model call for final user-visible response

### Tool/Delegation Format
- MCP tools are converted to OpenAI `tools` format via `_build_tools_param()`
- Sub-agents are exposed as `delegate_to_{agent_name}` tool functions (both modes)
- Unavailable sub-agents (failed init) are automatically excluded from tool registration
- Multiple tool calls in native mode are executed in parallel via `asyncio.gather()`
- `_extract_tool_calls()` checks `response.tool_calls` first (works for both modes + mocks), then falls back to content JSON parsing in string mode
- Mode-specific behavior is encapsulated in 4 self-contained methods:
  - `_extract_tool_calls()`: prefers structured `response.tool_calls`, falls back to `_parse_action()` in string mode
  - `_build_assistant_msg()`: formats assistant message with or without `tool_calls` array
  - `_append_tool_result()`: uses `role: tool` (native) or `role: user` (string)
  - `_build_system_prompt()`: injects text-based tool descriptions only in string mode

### Key Classes
- `ToolCall(id, name, arguments)`: Represents a single tool call. Arguments auto-normalize from JSON string or dict via `__post_init__`
- `ModelResponse(content, tool_calls, finish_reason)`: Structured response from `ModelAPI.process_message()`

### Phase 2 Final Response
- Phase 1 is skipped entirely when no tools/agents or max_steps=0
- Phase 2 always calls the model for the final response
- "Provide your final response based on information gathered" instruction is only injected when tools/delegations were executed
- Streaming or non-streaming based on the original request
- Both delegation and regular tool calls emit `tool_call` memory events before execution

### Validation & Error Handling
- `max_steps=0` is valid (disables reasoning/Phase 1)
- Empty model responses (no content, no tool_calls) log warnings and store `format_warning` memory events
- Malformed tool call arguments (invalid JSON) log warnings and default to `{}`

### Mock Response Pattern
For testing, use `DEBUG_MOCK_RESPONSES` with tool_calls JSON or plain text.
The `tool_calls` format works in both native and string mode (structured tool_calls are checked first regardless of mode).
Response count depends on whether Phase 1 runs:
```bash
# No tools/agents: Phase 1 skipped, only Phase 2 (1 entry)
export DEBUG_MOCK_RESPONSES='["Hello, world!"]'

# With tools (both modes): tool call → loop break → Phase 2 final (3 entries)
export DEBUG_MOCK_RESPONSES='["{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"hi\"}}]}", "No more actions.", "Done."]'

# String mode alternative: JSON action in content → no action text → Phase 2 final (3 entries)
export DEBUG_MOCK_RESPONSES='["{\"tool\": \"echo\", \"arguments\": {\"message\": \"hi\"}}", "No more actions needed.", "Done."]'
```

## Testing Patterns
- Use `DEBUG_MOCK_RESPONSES` for deterministic tests
- Tests use `pytest-asyncio` for async test functions
- Use `@pytest.mark.parametrize` for testing multiple cases
- Mock responses with `tool_calls` key work in both native and string mode
- String mode also supports `{"tool": "name", "arguments": {...}}` content format as fallback
- Absence of tool_calls signals loop completion (both modes)
- Agents with tools: N+1 mock responses (N for Phase 1 steps + 1 for Phase 2 final)
- Agents without tools: 1 mock response (Phase 2 only)
- Native tests use `_make_native_agent()` helper to set `_supports_native_tools=True`
- String tests set `agent._supports_native_tools = False` after construction

## Code Style
- Use `black` for formatting
- Use `ty` for type checking
- Prefer async/await patterns
- Minimal comments (only when clarification needed)

## API Endpoints
- `GET /health`: Health probe
- `GET /ready`: Readiness probe  
- `GET /.well-known/agent`: A2A agent card
- `POST /v1/chat/completions`: OpenAI-compatible chat endpoint
