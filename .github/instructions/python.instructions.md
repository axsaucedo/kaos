---
applyTo: "data-plane/kaos-framework/**"
---

# Python Agent Framework Instructions

Built on **Pydantic AI** — the framework wraps `pydantic_ai.Agent` with KAOS-specific functionality (env-var config, memory, delegation, telemetry).

## Quick Reference
```bash
cd data-plane/kaos-framework
source .venv/bin/activate
python -m pytest tests/ -v      # Run all tests
make lint                       # Run linting (black + ty check)
make format                     # Auto-format code
```

## Project Structure
- `agent/client.py`: Agent (wraps pydantic_ai.Agent), RemoteAgent, AgentCard, _MockResponseState
- `agent/server.py`: FastAPI HTTP server with health probes, memory endpoints, chat completions, A2A discovery
- `agent/memory.py`: LocalMemory, RedisMemory, NullMemory for session/event management (unchanged)
- `agent/telemetry/`: OpenTelemetry instrumentation (tracing, metrics)
- `pyproject.toml`: Dependencies — `pydantic-ai`, `fasta2a`, `opentelemetry-*`

**Removed modules** (replaced by Pydantic AI native support):
- `mcptools/` — MCP handled via `pydantic_ai.mcp.MCPServerStreamableHTTP`
- `modelapi/` — Model API handled via `pydantic_ai.models.openai.OpenAIChatModel`

## Key Environment Variables
| Variable | Description |
|----------|-------------|
| `AGENT_NAME` | Agent name (required) |
| `MODEL_API_URL` | LLM API base URL (required) |
| `MODEL_NAME` | Model name (required) |
| `AGENT_SYSTEM_PROMPT` | System prompt for the agent |
| `AGENT_SUB_AGENTS` | Direct format: `"name:url,name:url"` |
| `AGENT_DESCRIPTION` | Agent description for A2A card |
| `MCP_SERVERS` | Comma-separated MCP server names |
| `MCP_SERVER_<NAME>_URL` | URL for each MCP server |
| `MEMORY_TYPE` | Memory backend: `local` (default) or `redis` |
| `MEMORY_REDIS_URL` | Redis connection URL (required when `MEMORY_TYPE=redis`) |
| `DEBUG_MOCK_RESPONSES` | JSON array of mock responses (tool_calls JSON or plain text) |
| `OTEL_ENABLED` | Enable OpenTelemetry instrumentation |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP exporter endpoint |

**Removed:** `TOOL_CALL_MODE` — Pydantic AI always uses native tool calling (no string mode).

## Architecture

### Core: Pydantic AI Agent Wrapper
The KAOS `Agent` class wraps `pydantic_ai.Agent`:
- Model configured via `OpenAIChatModel(model_name, provider=OpenAIProvider(base_url=MODEL_API_URL))`
- MCP servers passed as `toolsets=[MCPServerStreamableHTTP(url)]` to Pydantic AI
- Sub-agent delegation registered as `@agent.tool_plain` functions with `delegate_to_` prefix
- Agentic loop handled entirely by Pydantic AI (no custom loop code)

### Tool Calling
- Pydantic AI uses native function calling exclusively (no string-mode concept)
- MCP tools: `MCPServerStreamableHTTP(url + "/mcp")` — `/mcp` path appended for FastMCP servers
- Delegation tools: `delegate_to_{agent_name}` registered as plain tool functions
- Tool discovery for agent card: connects to MCP servers via `list_tools()` on card requests

### Memory Bridge
- KAOS memory (Local/Redis/Null) persists across sessions — Pydantic AI has no built-in persistence
- `_convert_kaos_events_to_pydantic()`: KAOS events → Pydantic AI `ModelRequest`/`ModelResponse` messages
- `_store_pydantic_message()`: Pydantic AI messages → KAOS memory events
- Memory event types for delegation: `delegation_request`/`delegation_response` (not `tool_call`/`tool_result`)
- Incoming task-delegation: detected via `task-delegation` role → stored as `task_delegation_received`

### Key Classes
- `Agent`: Main wrapper — `process_message()`, `process_message_stream()`, `get_agent_card()`
- `RemoteAgent`: Represents a peer agent for delegation (stores URL, optional AgentCard)
- `AgentCard`: A2A discovery card with name, description, URL, skills
- `_MockResponseState`: Mutable mock response state shared via closure (workaround for ContextVar + FunctionModel issue)

## Mock Response Pattern
For testing, `DEBUG_MOCK_RESPONSES` creates a `FunctionModel` that returns responses in sequence.

```bash
# No tools/agents: only final response (1 entry)
export DEBUG_MOCK_RESPONSES='["Hello, world!"]'

# With tools: tool call → final answer (2 entries)
export DEBUG_MOCK_RESPONSES='["{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"hi\"}}]}", "Done."]'

# Delegation: delegate → final answer (2 entries)
export DEBUG_MOCK_RESPONSES='["{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"delegate_to_worker\", \"arguments\": {\"task\": \"do it\"}}]}", "Worker finished."]'
```

**Key difference from old framework:** Tool calls need 2 mock responses (not 3). Pydantic AI stops automatically after text follows tool execution. E2E tests with 3 entries still work (3rd is unused).

### ContextVar Bug Workaround
Pydantic AI runs `FunctionModel` handlers in a copied context — `ContextVar` state doesn't persist across calls. Solution: `_MockResponseState` class (mutable object captured by closure) instead of `ContextVar[List[str]]`.

## Testing Patterns
- Use `DEBUG_MOCK_RESPONSES` for deterministic tests
- Tests use `pytest-asyncio` for async test functions
- `FunctionModel` from `pydantic_ai.models.function` for custom mock behavior
- `TestModel` from `pydantic_ai.models.test` for simple predetermined responses
- Agents with tools: 2 mock responses (tool call + final answer)
- Agents without tools: 1 mock response (final answer only)
- No string-mode tests — Pydantic AI always uses native tool calling

## Code Style
- Use `black` for formatting
- Use `ty` for type checking
- Prefer async/await patterns
- Minimal comments (only when clarification needed)

## API Endpoints
- `GET /health`: Health probe
- `GET /ready`: Readiness probe
- `GET /.well-known/agent`: A2A agent card (discovers tools from MCP servers)
- `POST /v1/chat/completions`: OpenAI-compatible chat endpoint
- `GET /memory/events?session_id=X`: Memory events for a session
- `GET /memory/sessions`: List all memory sessions
