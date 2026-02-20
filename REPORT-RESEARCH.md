# KAOS Pydantic AI Integration — Research Report

## 1. Executive Summary

This report documents the findings from a comprehensive codebase analysis of KAOS's Python data-plane (`data-plane/kaos-framework/`) and Pydantic AI's capabilities. The goal is to determine exactly what must be built, preserved, adapted, or removed to replace the custom Python agent framework with Pydantic AI as a first-class citizen.

**Conclusion:** Pydantic AI is a strong fit. Its native MCP support, `to_a2a()` via FastA2A, OpenAI-compatible model providers, and type-safe design align well with KAOS. The main integration work is bridging KAOS's operator-injected environment variables, memory system, telemetry, and HTTP API surface to Pydantic AI's patterns.

---

## 2. Current Codebase Analysis

### 2.1 Module Inventory

| Module | File | Lines | Role |
|--------|------|-------|------|
| Agent Loop | `agent/client.py` | ~993 | Two-phase agentic loop (tool calling → final response), delegation, MCP tool execution |
| Agent Server | `agent/server.py` | ~705 | FastAPI server with OpenAI-compatible API, health probes, memory endpoints, A2A discovery |
| Memory | `agent/memory.py` | ~726 | LocalMemory (in-process), RedisMemory (distributed), NullMemory (stateless) |
| Model API | `modelapi/client.py` | ~303 | OpenAI-compatible async HTTP client via httpx, mock response support |
| MCP Tools | `mcptools/client.py` | ~183 | MCP SDK client for tool discovery and execution via Streamable HTTP |
| Telemetry | `telemetry/manager.py` | ~625 | Singleton OTel manager with inline span management, metrics, log correlation |

### 2.2 Key Design Patterns

1. **Env-Var Driven Configuration**: The Go operator injects 15+ environment variables into agent pods (AGENT_NAME, MODEL_API_URL, MODEL_NAME, MCP_SERVERS, PEER_AGENTS, MEMORY_TYPE, OTEL_*, etc.). The `AgentServerSettings` (pydantic BaseSettings) reads these.

2. **Two-Phase Agentic Loop**:
   - Phase 1: Non-streaming tool calling loop (up to `max_steps`). Uses native OpenAI function calling OR string-based JSON parsing depending on model capability.
   - Phase 2: Streaming/non-streaming final response to user.

3. **Memory Event System**: Custom `MemoryEvent` dataclass tracks events per session (`user_message`, `agent_response`, `tool_call`, `tool_result`, `delegation_request`, `delegation_response`, etc.). Events are exposed via `/memory/events` and `/memory/sessions` HTTP endpoints.

4. **A2A Communication**: Custom implementation on top of `/v1/chat/completions`. `RemoteAgent` discovers peer agent cards via `/.well-known/agent`, delegates via HTTP POST with `role: "task-delegation"`. Not A2A-protocol compliant.

5. **DEBUG_MOCK_RESPONSES**: JSON array env var for deterministic testing. Returns mock `ModelResponse` objects with tool_calls or plain text. Used extensively in both unit and E2E tests.

### 2.3 Test Inventory

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `tests/test_agent.py` | ~20 | Agent creation, memory (Local/Null/Redis), message processing, session management, mock responses |
| `tests/test_agentic_loop.py` | ~40 | Tool calling (native + string mode), delegation, max steps, streaming, parallel tool execution |
| `tests/test_agent_server.py` | ~5 | HTTP server integration (requires Ollama) |
| `tests/test_telemetry.py` | ~10 | OTel span management, metrics, context propagation |
| `operator/tests/e2e/` | ~20 | Full K8s E2E tests (agent creation, MCP tools, multi-agent delegation) |

### 2.4 Operator Integration Surface

The Go operator (`operator/controllers/agent_controller.go`) constructs agent pods with:
- Container image: `DEFAULT_AGENT_IMAGE` env var (overridable via `spec.container.image`)
- Entrypoint: `python -m uvicorn agent.server:get_app --factory --host 0.0.0.0 --port 8000`
- Health probes: `/health` (liveness), `/ready` (readiness)
- Port: 8000
- Environment variables: 15+ injected from CRD spec fields

---

## 3. Pydantic AI Capabilities Assessment

### 3.1 Feature Mapping

| KAOS Feature | Pydantic AI Equivalent | Gap / Notes |
|--------------|----------------------|-------------|
| Agent loop (tool calling) | `pydantic_ai.Agent` with tools | ✅ Native. Pydantic AI handles tool calling natively with type-safe tools |
| Native + string tool calling modes | Auto-detected by Pydantic AI per model | ✅ Pydantic AI handles this internally |
| MCP tool integration | `pydantic_ai.mcp.MCPServerHTTP` | ✅ Native MCP client support. Can connect to KAOS MCPServers |
| Sub-agent delegation | `delegate_to_` tool pattern | ⚠️ Need custom implementation. Pydantic AI doesn't have built-in delegation; use tool functions that call remote agents |
| A2A discovery | `agent.to_a2a()` via FastA2A | ✅ Native. Exposes `/.well-known/agent.json` (A2A spec compliant) |
| OpenAI-compatible API | FastA2A or custom FastAPI wrapper | ⚠️ FastA2A uses A2A protocol, not `/v1/chat/completions`. Need wrapper for backward compat |
| Streaming (SSE) | Pydantic AI `agent.run_stream()` | ✅ Native streaming support |
| Memory (Local/Redis/Null) | `message_history` parameter | ⚠️ Pydantic AI uses message list, not event store. Need bridge layer for KAOS memory |
| Memory HTTP endpoints | Custom FastAPI routes | ⚠️ Not provided by Pydantic AI. Must be retained as custom routes |
| OTel instrumentation | Pydantic AI emits OTel spans | ⚠️ Uses Logfire by default. Need to configure for raw OTel export |
| Model API (OpenAI-compatible) | `OpenAIModel(base_url=...)` | ✅ Native. Pydantic AI supports custom OpenAI-compatible endpoints |
| DEBUG_MOCK_RESPONSES | `TestModel` / `FunctionModel` | ✅ Pydantic AI has `TestModel` for deterministic testing |
| Health/readiness probes | Custom FastAPI routes | ⚠️ Must add to the server wrapper |
| Max steps limit | `pydantic_ai.Agent(max_result_retries=N)` | ⚠️ Different semantics. Pydantic AI controls retries, not tool loop steps. May need custom wrapper |

### 3.2 Model Provider Integration

KAOS currently uses a custom `ModelAPI` client (httpx-based, OpenAI-compatible). Pydantic AI provides:
- `OpenAIModel(model_name, provider=OpenAIProvider(base_url=..., api_key=...))` — connects to any OpenAI-compatible server
- This replaces both `modelapi/client.py` and the LiteLLM dependency for basic routing
- For advanced routing (fallback), LiteLLM can still be used via the `pydantic-ai-litellm` package

### 3.3 A2A Protocol

Pydantic AI provides `agent.to_a2a()` which creates an ASGI app implementing the A2A protocol spec:
- `/.well-known/agent.json` discovery endpoint
- Task-based communication (create, track, cancel)
- Streaming support
- This replaces KAOS's custom `/.well-known/agent` endpoint and `/v1/chat/completions` delegation

### 3.4 MCP Support

Pydantic AI has native MCP client support:
```python
from pydantic_ai.mcp import MCPServerHTTP
server = MCPServerHTTP(url="http://mcp-server:8000/mcp")
agent = Agent("openai:gpt-4o", mcp_servers=[server])
```
This replaces `mcptools/client.py` entirely.

---

## 4. Integration Architecture

### 4.1 Approach: Replace Custom Framework, Keep Infrastructure

The integration strategy is to replace the custom agentic loop, model client, and MCP client with Pydantic AI, while keeping the KAOS-specific infrastructure:

**Replace with Pydantic AI:**
- `agent/client.py` (Agent, RemoteAgent, AgentCard) → `pydantic_ai.Agent` + custom delegation tools
- `modelapi/client.py` (ModelAPI) → `pydantic_ai.models.openai.OpenAIModel`
- `mcptools/client.py` (MCPClient) → `pydantic_ai.mcp.MCPServerHTTP`

**Keep / Adapt:**
- `agent/server.py` (AgentServer) → Rewrite as thin wrapper around Pydantic AI agent
- `agent/memory.py` (LocalMemory, RedisMemory, NullMemory) → Bridge to Pydantic AI `message_history`
- `telemetry/manager.py` → Keep for KAOS-specific OTel configuration; Pydantic AI handles agent-level spans

**Keep Unchanged:**
- All operator Go code (CRD types, controller, env var injection)
- Dockerfile structure (though CMD may change)
- E2E test patterns (though mock mechanism changes)

### 4.2 Server Architecture

```
┌─────────────────────────────────────────┐
│  KAOS Agent Pod (Port 8000)             │
│                                         │
│  ┌─────────────────────────────┐        │
│  │  FastAPI Server (wrapper)   │        │
│  │  /health, /ready            │        │
│  │  /v1/chat/completions       │─┐      │
│  │  /memory/events, /sessions  │ │      │
│  │  /.well-known/agent.json    │ │      │
│  └─────────────────────────────┘ │      │
│                                  │      │
│  ┌──────────────────────┐        │      │
│  │  pydantic_ai.Agent   │◄───────┘      │
│  │  - MCP tools (native)│               │
│  │  - Delegation tools  │               │
│  │  - OpenAI model      │               │
│  └──────────────────────┘               │
│                                         │
│  ┌──────────────────────┐               │
│  │  KAOS Memory Bridge  │               │
│  │  Local/Redis/Null    │               │
│  └──────────────────────┘               │
│                                         │
│  ┌──────────────────────┐               │
│  │  KAOS OTel Manager   │               │
│  └──────────────────────┘               │
└─────────────────────────────────────────┘
```

### 4.3 Environment Variable Contract

No changes to the operator. The Python wrapper reads the same env vars:

| Env Var | Used For |
|---------|----------|
| `AGENT_NAME` | Agent name |
| `MODEL_API_URL` | Pydantic AI `OpenAIModel(provider=OpenAIProvider(base_url=...))` |
| `MODEL_NAME` | Model identifier |
| `MCP_SERVERS` + `MCP_SERVER_<name>_URL` | `MCPServerHTTP` instances |
| `PEER_AGENTS` + `PEER_AGENT_<name>_CARD_URL` | Delegation tool functions |
| `MEMORY_*` | Memory backend selection and config |
| `OTEL_*` | Telemetry configuration |
| `DEBUG_MOCK_RESPONSES` | `TestModel` / custom mock |

### 4.4 Custom Image Support

Two modes for users:
1. **Template mode**: Users provide a Pydantic AI agent definition (Python file), KAOS wraps it with the standard server, memory, and OTel infrastructure
2. **Full custom mode**: Users build their own image using KAOS utility functions (`kaos.enable_otel()`, `kaos.enable_memory()`, `kaos.serve()`)

---

## 5. Key Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Pydantic AI pre-1.0 breaking changes | MEDIUM | Pin version, wrap behind KAOS interfaces |
| Memory bridging complexity | MEDIUM | Implement bridge that converts Pydantic AI messages ↔ KAOS MemoryEvents |
| A2A backward compatibility | HIGH | Keep `/v1/chat/completions` endpoint alongside A2A protocol |
| DEBUG_MOCK_RESPONSES pattern change | MEDIUM | Implement adapter for Pydantic AI `TestModel` that reads same env var format |
| E2E test breakage | HIGH | Ensure same HTTP API surface; operator doesn't change |
| OTel span naming changes | LOW | Pydantic AI uses standard OTel; KAOS-specific metrics via wrapper |

---

## 6. Dependencies to Add

```
pydantic-ai[mcp]       # Core agent framework + MCP support
fasta2a                 # A2A protocol implementation (by Pydantic team)
```

**Dependencies to Remove (replaced by Pydantic AI):**
```
litellm                 # Replaced by Pydantic AI model providers
fastmcp                 # Replaced by pydantic-ai MCP support
```

**Dependencies to Keep:**
```
fastapi, uvicorn        # HTTP server (wrapper)
redis                   # Distributed memory
opentelemetry-*         # Observability
httpx                   # HTTP client (for delegation, health checks)
pydantic, pydantic-settings  # Already a dependency of Pydantic AI
sse-starlette           # SSE streaming
```

---

## 7. Questions Resolved During Research

1. **Q: Does Pydantic AI support OpenAI-compatible endpoints?**
   A: Yes, via `OpenAIModel(model_name, provider=OpenAIProvider(base_url=url))`.

2. **Q: How does Pydantic AI handle MCP?**
   A: Native support via `MCPServerHTTP(url=...)`, auto-discovers tools.

3. **Q: Can Pydantic AI do A2A?**
   A: Yes, via `agent.to_a2a()` which creates a FastA2A ASGI app.

4. **Q: How does Pydantic AI handle conversation memory?**
   A: Via `message_history` parameter on `agent.run()`. Messages are serializable. No built-in persistence — KAOS must bridge to its own Redis/Local memory.

5. **Q: How does Pydantic AI handle tool calling?**
   A: Natively via decorated functions. Auto-generates OpenAI tool schemas from type hints.

6. **Q: Does Pydantic AI support streaming?**
   A: Yes, via `agent.run_stream()` which yields structured streaming events.

7. **Q: How does Pydantic AI handle OTel?**
   A: Emits standard OTel spans. Can configure custom tracer provider.

8. **Q: How does testing work without real LLMs?**
   A: `TestModel` returns predetermined responses. `FunctionModel` allows custom logic.

---

*Research completed: 2026-02-20*
*Codebase version: 0.2.8-dev (commit aaf6fb3)*
