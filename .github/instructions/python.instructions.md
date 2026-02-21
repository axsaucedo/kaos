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
- `agent/string_mode.py`: String-mode FunctionModel wrapper for models without native function calling
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
| `TOOL_CALL_MODE` | Tool calling mode: `auto` (default), `native`, `string` |
| `OTEL_ENABLED` | Enable OpenTelemetry instrumentation |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP exporter endpoint |

## Architecture

### Core: Pydantic AI Agent Wrapper
The KAOS `Agent` class wraps `pydantic_ai.Agent`:
- Model configured via `OpenAIChatModel(model_name, provider=OpenAIProvider(base_url=MODEL_API_URL + "/v1"))`
- `/v1` is auto-appended to `MODEL_API_URL` if not present (required for Ollama OpenAI-compat endpoint)
- MCP servers passed as `toolsets=[MCPServerStreamableHTTP(url)]` to Pydantic AI
- Sub-agent delegation registered as `@agent.tool_plain` functions with `delegate_to_` prefix
- Agentic loop handled entirely by Pydantic AI (no custom loop code)

### Tool Calling
- Pydantic AI uses native function calling by default
- `TOOL_CALL_MODE=string`: FunctionModel wrapper injects tool descriptions into system prompt, parses JSON tool calls from text
- `TOOL_CALL_MODE=auto|native`: Standard Pydantic AI native function calling (default)
- MCP tools: `MCPServerStreamableHTTP(url + "/mcp")` — `/mcp` path appended for FastMCP servers
- Delegation tools: `delegate_to_{agent_name}` registered as plain tool functions
- Delegation forwards recent conversation context from memory to sub-agents
- Tool discovery for agent card: connects to MCP servers via `list_tools()` on card requests
- Native Pydantic AI tools (from custom_pydantic_agent) also exposed in agent card via `_function_toolset`
- `max_steps` controls model call limit via `UsageLimits(request_limit=max_steps)` (not `retries`)

### String Mode (`agent/string_mode.py`)
- For models without native function calling support (e.g., small Ollama models)
- `build_string_mode_handler(base_url, model_name)` → FunctionModel handler
- Injects tool descriptions + JSON format instructions into system prompt
- Parses `{"tool_calls": [...]}` JSON from model response text
- Returns `ToolCallPart` objects when tool calls detected, `TextPart` otherwise
- Controlled via `TOOL_CALL_MODE` env var (CRD: `spec.config.toolCallMode`)

### Custom Agent Image Pattern
- Users create custom Pydantic AI agents with their own tools
- Use `create_agent_server(custom_agent=my_agent)` to wrap with KAOS endpoints
- Deploy via Agent CRD with `container.image` override
- Example: `examples/custom-agent/server.py`

### Memory Bridge
- KAOS memory (Local/Redis/Null) persists across sessions — Pydantic AI has no built-in persistence
- `_build_message_history()`: KAOS events → Pydantic AI `ModelRequest`/`ModelResponse` messages
- `_store_pydantic_message()`: Pydantic AI messages → KAOS memory events
- Memory event types for delegation: `delegation_request`/`delegation_response` (not `tool_call`/`tool_result`)
- Incoming task-delegation: detected via `task-delegation` role → stored as `task_delegation_received`
- `memory_enabled` flag gates all memory reads/writes (set `False` for stateless agents)
- `memory_context_limit` caps history size passed to model (default 6)
- Streaming and non-streaming paths both persist tool/delegation events via `result.new_messages()`
- History exclusion: latest prompt event explicitly excluded (not fragile `events[:-1]`)

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
- String-mode tests in `tests/test_string_mode.py` — tool description generation, JSON parsing, agent integration

## Code Style
- Use `black` for formatting
- Use `ty` for type checking
- Prefer async/await patterns
- Minimal comments (only when clarification needed)

## OpenTelemetry
- Pydantic AI instrumentation enabled via `instrument=True` on Agent and `Agent.instrument_all(True)` in server startup
- KAOS's `KaosOtelManager` handles SDK init, custom spans, metrics, context propagation
- Pydantic AI uses the global `TracerProvider` set by KAOS — spans auto-parent correctly
- Per-tool spans exist in both KAOS (iter loop) and Pydantic AI (`_tool_manager.py`) — some redundancy
- See `PLAN-FULL-OTEL-REFACTOR.md` (gitignored) for future migration plan to simplify KAOS OTEL code
- See `REPORT-PYDANTIC-TELEMETRY-FULL.md` (gitignored) for deep-dive into Pydantic AI internals

## API Endpoints
- `GET /health`: Health probe
- `GET /ready`: Readiness probe
- `GET /.well-known/agent`: A2A agent card (discovers tools from MCP servers)
- `POST /v1/chat/completions`: OpenAI-compatible chat endpoint
- `GET /memory/events?session_id=X`: Memory events for a session
- `GET /memory/sessions`: List all memory sessions
