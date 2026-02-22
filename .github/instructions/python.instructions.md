---
applyTo: "data-plane/kaos-framework/**"
---

# Python Agent Framework Instructions

Built on **Pydantic AI** — `AgentServer` is the central orchestration component. Pydantic AI is the core agent runtime; KAOS adds server/enterprise capabilities (env-var config, memory, delegation, telemetry, A2A discovery).

## Quick Reference
```bash
cd data-plane/kaos-framework
source .venv/bin/activate
python -m pytest tests/ -v      # Run all tests
make lint                       # Run linting (black + ty check)
make format                     # Auto-format code
```

## Project Structure
- `agent/server.py`: AgentServer, create_agent_server(), routes, _process_message(), AgentDeps, AgentCard, RemoteAgent, model resolution
- `agent/tools.py`: DelegationToolset (AbstractToolset), execute_delegation, format_progress_event, build_string_mode_handler
- `agent/memory.py`: Memory ABC, LocalMemory, RedisMemory, NullMemory + build_message_history/store_pydantic_message utilities
- `agent/telemetry/`: OpenTelemetry instrumentation (tracing, metrics)
- `pyproject.toml`: Dependencies — `pydantic-ai`, `opentelemetry-*`

**Module layout rationale:**
- `server.py` owns everything that creates/runs agents: AgentServer, create_agent_server(), RemoteAgent (HTTP client for sub-agents), model resolution, request lifecycle
- `tools.py` owns tool extensions: DelegationToolset (AbstractToolset subclass), string-mode model handler, progress event formatting
- `memory.py` owns persistence: Memory ABC + all backends, plus build_message_history/store_pydantic_message utilities on the base class

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
| `OTEL_INSTRUMENTATION_VERSION` | Pydantic AI instrumentation version: 1-4 (default: `4`) |
| `OTEL_EVENT_MODE` | Pydantic AI event mode: `attributes` (default) or `logs` (forces v1) |

## Architecture

### Core: AgentServer + create_agent_server()
`AgentServer` is the central component — it owns a `pydantic_ai.Agent` instance and provides KAOS enterprise capabilities:
- `create_agent_server(settings, custom_agent)` is the main factory: resolves model, memory, delegation, MCP, OTEL
- Model configured via `OpenAIChatModel(model_name, provider=OpenAIProvider(base_url=MODEL_API_URL + "/v1"))`
- `/v1` is auto-appended to `MODEL_API_URL` if not present (required for Ollama OpenAI-compat endpoint)
- MCP servers passed as `toolsets=[MCPServerStreamableHTTP(url)]` to Pydantic AI
- Sub-agent delegation via `DelegationToolset` (AbstractToolset subclass) in `toolsets=[...]`
- Agentic loop handled entirely by Pydantic AI (no custom loop code)

### Delegation via DelegationToolset (tools.py)
- `DelegationToolset` extends `AbstractToolset[AgentDeps]` — the same pattern as `MCPServerStreamableHTTP`
- Exposes sub-agents as `delegate_to_{agent_name}` tools dynamically (inactive agents excluded per-run)
- `execute_delegation()` calls `RemoteAgent.process_message()` with conversation context
- Progress events emitted via `format_progress_event()` during tool execution

### Tool Calling
- Pydantic AI uses native function calling by default
- `TOOL_CALL_MODE=string`: FunctionModel wrapper injects tool descriptions into system prompt, parses JSON tool calls from text
- `TOOL_CALL_MODE=auto|native`: Standard Pydantic AI native function calling (default)
- MCP tools: `MCPServerStreamableHTTP(url + "/mcp")` — `/mcp` path appended for FastMCP servers
- `max_steps` controls model call limit via `UsageLimits(request_limit=max_steps)` (not `retries`)

### String Mode (tools.py)
- For models without native function calling support (e.g., small Ollama models)
- `build_string_mode_handler(base_url, model_name)` → FunctionModel handler
- Injects tool descriptions + JSON format instructions into system prompt
- Parses `{"tool_calls": [...]}` JSON from model response text
- Returns `ToolCallPart` objects when tool calls detected, `TextPart` otherwise
- Controlled via `TOOL_CALL_MODE` env var (CRD: `spec.config.toolCallMode`)

### Custom Agent Image Pattern
- Users create custom Pydantic AI agents with their own tools
- Use `create_agent_server(custom_agent=my_agent)` to wrap with KAOS endpoints
- KAOS overrides the model and adds DelegationToolset to custom agents
- Deploy via Agent CRD with `container.image` override
- Example: `examples/custom-agent/server.py`

### Memory (memory.py)
- KAOS memory (Local/Redis/Null) persists across sessions — Pydantic AI has no built-in persistence
- All implementations extend `Memory` ABC with `build_message_history()` and `store_pydantic_message()` as concrete methods
- NullMemory is a no-op — always call memory methods regardless (no branching needed)
- `build_message_history(session_id, context_limit)`: KAOS events → Pydantic AI `ModelRequest`/`ModelResponse` messages
- `store_pydantic_message(session_id, msg)`: Pydantic AI messages → KAOS memory events
- Memory event types for delegation: `delegation_request`/`delegation_response` (not `tool_call`/`tool_result`)
- Incoming task-delegation: detected via `task-delegation` role → stored as `task_delegation_received`
- `memory_context_limit` caps history size passed to model (default 6)
- Streaming and non-streaming paths both persist tool/delegation events via `result.new_messages()`

### Dependency Injection
- `AgentDeps(session_id, memory)` passed via Pydantic AI `RunContext` to tools
- DelegationToolset uses `ctx.deps` for concurrency-safe session and memory access
- Custom tools registered on the Pydantic AI agent can also use `ctx: RunContext[AgentDeps]`

### Key Classes
- `AgentServer`: Central server — owns pydantic_ai.Agent, memory, routes, `_process_message()`
- `AgentDeps`: Per-run dependencies (session_id, memory) injected via RunContext
- `DelegationToolset`: AbstractToolset that exposes sub-agents as delegate_to_ tools
- `RemoteAgent`: HTTP client for sub-agent delegation (stores URL, optional AgentCard)
- `AgentCard`: A2A discovery card (uses `asdict()` for serialization)
- `Memory`: ABC interface for LocalMemory, RedisMemory, NullMemory (includes `close()`)
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
- `make_test_server()` in `tests/helpers.py` creates AgentServer instances for tests
- Agents with tools: 2 mock responses (tool call + final answer)
- Agents without tools: 1 mock response (final answer only)
- String-mode tests in `tests/test_string_mode.py` — tool description generation, JSON parsing

## Code Style
- Use `black` for formatting
- Use `ty` for type checking
- Prefer async/await patterns
- Minimal comments (only when clarification needed)

## OpenTelemetry
- Pydantic AI instrumentation configured via `Agent.instrument_all(InstrumentationSettings(...))` in server startup
- **Important**: Do NOT pass `instrument=True` to PydanticAgent constructor — it creates fresh defaults, ignoring `instrument_all()` settings. Leave as `None` to use class-level defaults.
- `OTEL_INSTRUMENTATION_VERSION` (default: 4) and `OTEL_EVENT_MODE` (default: attributes) control Pydantic AI behavior
- `telemetry/manager.py` provides: `init_otel()` (SDK setup), `get_tracer()`, `get_delegation_metrics()`, `inject_trace_context()`, `extract_trace_context()`
- Pydantic AI handles agent/model/tool spans internally; KAOS adds delegation spans and `server-run` request span
- `server-run` span created inside `generate_stream()` (streaming) and `_complete_chat_completion()` (non-streaming) to stay active during processing
- Context propagation: `tracer.start_as_current_span()` for delegation/server spans (no manual attach/detach)
- Delegation metrics: `kaos.delegations` counter + `kaos.delegation.duration` histogram
- Pydantic AI OTEL Logger API: version 1 + `event_mode='logs'` emits LogRecord events (gen_ai.system, gen_ai.user, gen_ai.choice); version 2+ stores data as span attributes only
- KAOS logs are correlated via `KaosLoggingHandler` (adds trace_id/span_id to log records)

## API Endpoints
- `GET /health`: Health probe
- `GET /ready`: Readiness probe
- `GET /.well-known/agent`: A2A agent card (discovers tools from MCP servers)
- `POST /v1/chat/completions`: OpenAI-compatible chat endpoint
- `GET /memory/events?session_id=X`: Memory events for a session
- `GET /memory/sessions`: List all memory sessions
