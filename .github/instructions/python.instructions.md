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

## Native Function Calling (Agentic Loop)

The agent uses native OpenAI function calling via the `tools` API:
1. **Phase 1 (Tool Calling)**: Non-streaming model calls with `tools` parameter. Model returns `tool_calls` in response to invoke MCP tools or delegate to sub-agents. Loops until model responds with content only (no tool_calls).
2. **Phase 2 (Final Response)**: Streaming model call for final user-visible response.

### Tool/Delegation Format
- MCP tools are converted to OpenAI `tools` format via `_build_tools_param()`
- Sub-agents are exposed as `delegate_to_{agent_name}` tool functions with a `task` string parameter
- Model returns structured `tool_calls` array — no JSON parsing from content text

### Key Classes
- `ToolCall(id, name, arguments)`: Represents a single tool call from model response
- `ModelResponse(content, tool_calls, finish_reason)`: Structured response from `ModelAPI.process_message()`

### Mock Response Pattern
For testing, use `DEBUG_MOCK_RESPONSES` with tool_calls JSON or plain text:
```bash
# Tool call then final response (2 entries, no {} needed)
export DEBUG_MOCK_RESPONSES='["{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"hi\"}}]}", "Done."]'
# Plain text response only
export DEBUG_MOCK_RESPONSES='["Hello, world!"]'
```

## Testing Patterns
- Use `DEBUG_MOCK_RESPONSES` for deterministic tests
- Tests use `pytest-asyncio` for async test functions
- Use `@pytest.mark.parametrize` for testing multiple cases
- Tool call mocks use `tool_calls` key, plain text mocks are just strings
- No `{}` no-action signal needed — absence of `tool_calls` signals completion

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
