---
applyTo: "pydantic-ai-server/**"
---

# Python Agent Framework Instructions

Built on **Pydantic AI** — `AgentServer` is the central orchestration component. Pydantic AI is the core agent runtime; KAOS adds server/enterprise capabilities (env-var config, memory, delegation, telemetry, A2A discovery).

## Quick Reference
```bash
cd pydantic-ai-server
source .venv/bin/activate
python -m pytest tests/ -v      # Run all tests
make lint                       # Run linting (black + ty check)
make format                     # Auto-format code
```

## Project Structure
- `pais/server.py`: AgentServer, create_agent_server(), routes, _run_agent(), _process_message(), logging
- `pais/serverutils.py`: AgentDeps, AgentCard (Pydantic BaseModel), AgentCardSkill, AgentCardCapabilities, RemoteAgent (A2A + chat delegation), AgentServerSettings, _resolve_model, response builders
- `pais/a2a.py`: TaskManager ABC, LocalTaskManager, NullTaskManager, Task/TaskState data model, JSON-RPC models/dispatcher/handlers, setup_a2a_routes()
- `pais/tools.py`: DelegationToolset (AbstractToolset), execute_delegation, format_progress_event, build_string_mode_handler
- `pais/memory.py`: Memory ABC, LocalMemory, RedisMemory, NullMemory + build_message_history/store_pydantic_message utilities
- `pais/telemetry.py`: OpenTelemetry instrumentation (tracing, metrics, SERVICE_NAME)
- `pyproject.toml`: Dependencies — `pydantic-ai`, `opentelemetry-*`

**Module layout rationale:**
- `server.py` owns the server lifecycle: AgentServer class, create_agent_server() factory, request routing
- `serverutils.py` owns data classes, settings, model resolution, RemoteAgent (A2A + chat delegation), response formatting helpers
- `a2a.py` owns A2A protocol: TaskManager ABC + LocalTaskManager/NullTaskManager, Task data model, JSON-RPC models/dispatcher/handlers, route setup
- `tools.py` owns tool extensions: DelegationToolset (AbstractToolset subclass), string-mode model handler, progress event formatting
- `memory.py` owns persistence: Memory ABC + all backends, plus build_message_history/store_pydantic_message utilities on the base class

## Key Environment Variables
| Variable | Description |
|----------|-------------|
| `AGENT_NAME` | Agent name (required) |
| `MODEL_API_URL` | LLM API base URL (required) |
| `MODEL_NAME` | Model name (required) |
| `AGENT_INSTRUCTIONS` | System prompt for the agent |
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
| `TASK_STORE_TYPE` | TaskManager backend: `local` (default) or `null` (disabled) |
| `AUTONOMOUS_ENABLED` | Enable startup-activated autonomous mode (default: `false`) |
| `AUTONOMOUS_GOAL` | Goal for startup-activated autonomous execution |
| `AUTONOMOUS_MAX_ITERATIONS` | Max autonomous loop iterations (default: `10`) |
| `AUTONOMOUS_MAX_RUNTIME_SECONDS` | Max wall-clock time for autonomous run (default: `300`) |
| `AUTONOMOUS_MAX_TOOL_CALLS` | Max cumulative tool calls across autonomous iterations (default: `50`) |

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
- MCP tools: `MCPServerStreamableHTTP(url + "/mcp")` — `/mcp` path appended for FastMCP 3.0 servers
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
- Example: `docs/examples/custom-agent.md` (uses `kaos agent init`/`build` CLI)

### Memory (memory.py)
- KAOS memory (Local/Redis/Null) persists across sessions — Pydantic AI has no built-in persistence
- All implementations extend `Memory` ABC with `build_message_history()` and `store_pydantic_message()` as concrete methods
- NullMemory is a no-op — always call memory methods regardless (no branching needed)
- `build_message_history(session_id, context_limit)`: KAOS events → Pydantic AI `ModelRequest`/`ModelResponse` messages
- `store_pydantic_message(session_id, msg)`: Pydantic AI messages → KAOS memory events
- Memory event types for delegation: `delegation_request`/`delegation_response` (not `tool_call`/`tool_result`)
- All delegation messages stored as `user_message` events (no special delegation role)
- `memory_context_limit` caps history size passed to model (default 6)
- Streaming and non-streaming paths both persist tool/delegation events via `result.new_messages()`

### Dependency Injection
- `AgentDeps(session_id, memory)` passed via Pydantic AI `RunContext` to tools
- DelegationToolset uses `ctx.deps` for concurrency-safe session and memory access
- Custom tools registered on the Pydantic AI agent can also use `ctx: RunContext[AgentDeps]`

### Key Classes
- `AgentServer`: Central server — owns pydantic_ai.Agent, memory, routes, `_run_agent()`, `_process_message()`
- `AgentDeps`: Per-run dependencies (session_id, memory) injected via RunContext
- `DelegationToolset`: AbstractToolset that exposes sub-agents as delegate_to_ tools
- `RemoteAgent`: HTTP client for sub-agent delegation — tries A2A SendMessage first, falls back to /v1/chat/completions
- `TaskManager`: ABC for task lifecycle — `send_message()`, `get_task()`, `cancel_task()`, `wait_for_completion()`, `shutdown()`
- `LocalTaskManager`: In-memory implementation with synchronous execution, OTel instrumentation
- `NullTaskManager`: No-op implementation (like NullMemory)
- `Task`: Task dataclass with id, session_id, status, history, metadata, timestamps
- `TaskState`: Enum — submitted, working, completed, failed, canceled
- `AgentCard`: A2A-compliant discovery card (Pydantic BaseModel with `alias_generator=to_camel`, `.to_dict()` uses `model_dump(by_alias=True)`)
- `AgentCardSkill`: A2A skill with id, name, description, tags, inputModes, outputModes
- `AgentCardCapabilities`: A2A capabilities (streaming, pushNotifications, stateTransitionHistory)
- `Memory`: ABC interface for LocalMemory, RedisMemory, NullMemory (includes `close()`)
- `JsonRpcRequest`/`JsonRpcResponse`/`JsonRpcError`: JSON-RPC 2.0 envelope models (in a2a.py)
- `_MockResponseState`: Mutable mock response state shared via closure (workaround for ContextVar + FunctionModel issue)

### TaskManager
- **TaskManager** ABC: `send_message()`, `submit_autonomous()`, `get_task()`, `cancel_task()`, `wait_for_completion()`, `shutdown()`
- **LocalTaskManager**: In-memory dict storage, synchronous process_fn execution, async autonomous execution, OTel spans/metrics
- **NullTaskManager**: No-op — `send_message()` returns a stub task, nothing persisted
- State transitions enforced via `VALID_TRANSITIONS` dict — terminal states allow no further transitions
- `TASK_STORE_TYPE` env var controls backend selection (`local` default, `null` to disable)
- Instrumented with OTel spans (`kaos.task.submit`, `kaos.task.execute`, `kaos.task.cancel`) and metrics (`kaos.tasks` counter, `kaos.task.duration` histogram)
- `submit_autonomous()`: Creates task with mode="autonomous", spawns `asyncio.create_task` for background execution
- `_running_tasks: Dict[str, asyncio.Task]` tracks running async tasks; `shutdown()` cancels all

### Autonomous Execution
- `LocalTaskManager._execute_autonomous(task, budgets)`: Core self-loop engine (owned by TaskManager)
- Iteratively calls `process_fn(message, session_id) → (response_text, tool_call_count)` with budget enforcement
- Completion detection: if `tool_call_count == 0` in an iteration, agent is done
- `AgentServer._run_agent(message, session_id) → (str, int)`: Shared helper used as `process_fn` callback
- Two activation modes:
  1. **Startup-activated**: `AUTONOMOUS_ENABLED=true` + `AUTONOMOUS_GOAL` → lifespan spawns task
  2. **A2A-triggered**: `SendMessage` with `configuration.mode: "autonomous"` + optional `budgets`
- `AutonomousBudgets` dataclass: `max_iterations` (10), `max_runtime_seconds` (300), `max_tool_calls` (50), `interval_seconds` (0)
- `TaskEvent` append-only event log per task: submitted, working, iteration.started/completed, budget.exhausted, completed/failed/canceled

### A2A JSON-RPC Endpoint (POST /) — a2a.py
- JSON-RPC 2.0 dispatcher at root path, separate from `/v1/chat/completions`
- A2A RC v1.0 methods: `SendMessage`, `GetTask`, `CancelTask` (PascalCase)
- Legacy aliases: `tasks/send`, `tasks/get`, `tasks/cancel` (backward compatible)
- `SendMessage` supports two modes: synchronous (default) returns completed/failed task, autonomous (`configuration.mode: "autonomous"`) spawns background task
- `contextId` param maps to session_id
- Standard error codes: -32700 (parse), -32600 (invalid request), -32601 (method not found), -32602 (invalid params), -32603 (internal), -32001 (task not found)
- A2A message format: `{role: "user"/"agent", parts: [{type: "text", text: "..."}]}`
- Agent card `stateTransitionHistory` dynamically reflects active TaskManager (not NullTaskManager)

### A2A Delegation (RemoteAgent)
- `RemoteAgent.process_message()` checks `supportedProtocols` from agent card
- If `"jsonrpc"` present: tries A2A `SendMessage`
- Falls back to `/v1/chat/completions` if A2A fails or unsupported
- Response extraction: artifacts → output → history (last agent message) → status.message

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
- `GET /.well-known/agent.json`: A2A-compliant agent card (discovers tools from MCP servers)
- `POST /v1/chat/completions`: OpenAI-compatible chat endpoint
- `POST /`: A2A JSON-RPC 2.0 endpoint (SendMessage, GetTask, CancelTask + legacy aliases)
- `GET /memory/events?session_id=X`: Memory events for a session
- `GET /memory/sessions`: List all memory sessions
