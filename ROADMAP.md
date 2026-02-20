# KAOS Pydantic AI Integration — Feature Roadmap

This roadmap lists **every feature** required for the Pydantic AI integration to be feature-complete (parity with the current custom framework, plus new capabilities).

---

## Feature Status Legend

- 🔴 **Not started** — Must be built
- 🟡 **Partial** — Pydantic AI covers some, KAOS bridge needed
- 🟢 **Native** — Pydantic AI provides this out of the box

---

## R1. Core Agent Framework

| ID   | Feature                                | Status | Notes                                                                                          |
| ---- | -------------------------------------- | ------ | ---------------------------------------------------------------------------------------------- |
| R1.1 | Pydantic AI Agent as core runtime      | 🔴     | Replace custom `Agent` class with `pydantic_ai.Agent`                                          |
| R1.2 | Env-var driven agent creation          | 🔴     | Read AGENT_NAME, MODEL_API_URL, MODEL_NAME, etc. to construct Pydantic AI Agent                |
| R1.3 | OpenAI-compatible model provider       | 🟢     | `OpenAIModel(provider=OpenAIProvider(base_url=...))`                                           |
| R1.4 | Tool calling (native function calling) | 🟢     | Pydantic AI handles natively                                                                   |
| R1.5 | String-mode tool calling fallback      | 🟡     | Pydantic AI has limited support; may need custom model wrapper for non-function-calling models |
| R1.6 | Max steps / loop control               | 🟡     | Pydantic AI has `max_result_retries`; custom logic for tool loop capping                       |
| R1.7 | System prompt configuration            | 🟢     | `Agent(system_prompt=...)`                                                                     |

## R2. MCP Tool Integration

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R2.1 | MCP server connection via Streamable HTTP | 🟢 | `MCPServerHTTP(url=...)` native |
| R2.2 | Multi-MCP server support | 🟢 | `Agent(mcp_servers=[...])` |
| R2.3 | Tool discovery from MCP servers | 🟢 | Automatic via Pydantic AI |
| R2.4 | Graceful degradation on MCP failure | 🟡 | Need error handling wrapper |
| R2.5 | Env-var MCP server configuration | 🔴 | Parse MCP_SERVERS + MCP_SERVER_*_URL env vars → MCPServerHTTP instances |

## R3. Sub-Agent Delegation

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R3.1 | Peer agent discovery via agent cards | 🔴 | Read PEER_AGENTS env var, fetch `/.well-known/agent.json` |
| R3.2 | Delegation as tool functions | 🔴 | Create `delegate_to_{name}` tools on Pydantic AI Agent |
| R3.3 | A2A-compatible delegation (send/receive tasks) | 🔴 | Use A2A protocol (JSON-RPC) for inter-agent communication |
| R3.4 | Unavailable agent exclusion | 🔴 | Skip agents that fail discovery at startup |

## R4. A2A Protocol

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R4.1 | A2A discovery endpoint (`/.well-known/agent.json`) | 🟢 | FastA2A provides this |
| R4.2 | A2A task execution (tasks/send) | 🟢 | FastA2A provides this |
| R4.3 | A2A streaming (tasks/sendSubscribe) | 🟢 | FastA2A provides this |
| R4.4 | Backward-compatible `/v1/chat/completions` | 🔴 | Wrap Pydantic AI agent in OpenAI-compatible endpoint |

## R5. HTTP Server / API Surface

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R5.1 | FastAPI/ASGI server | 🟡 | FastA2A is ASGI; need to mount additional routes |
| R5.2 | Health endpoint (`GET /health`) | 🔴 | Custom route on FastAPI wrapper |
| R5.3 | Readiness endpoint (`GET /ready`) | 🔴 | Custom route, checks model API connectivity |
| R5.4 | `/v1/chat/completions` (streaming + non-streaming) | 🔴 | OpenAI-compatible wrapper around Pydantic AI |
| R5.5 | `GET /memory/events` | 🔴 | Expose KAOS memory events via HTTP |
| R5.6 | `GET /memory/sessions` | 🔴 | Expose KAOS session list via HTTP |
| R5.7 | `GET /.well-known/agent.json` | 🟢 | FastA2A |
| R5.8 | Session ID from header/body | 🔴 | Parse X-Session-ID header or body field |

## R6. Memory System

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R6.1 | Memory event model (MemoryEvent, SessionMemory) | 🔴 | Preserve current dataclass structure |
| R6.2 | LocalMemory (in-process, bounded sessions) | 🔴 | Bridge Pydantic AI message_history to event store |
| R6.3 | RedisMemory (distributed, TTL, session index) | 🔴 | Bridge Pydantic AI message_history to Redis event store |
| R6.4 | NullMemory (stateless) | 🔴 | No-op implementation |
| R6.5 | Message history bridging (Pydantic AI ↔ KAOS events) | 🔴 | Convert between Pydantic AI `ModelRequest`/`ModelResponse` and KAOS `MemoryEvent` |
| R6.6 | Memory HTTP endpoints | 🔴 | Already covered by R5.5/R5.6 |
| R6.7 | Memory env var configuration | 🔴 | MEMORY_TYPE, MEMORY_REDIS_URL, MEMORY_MAX_SESSIONS, etc. |

## R7. Telemetry / Observability

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R7.1 | OTel tracing (spans for agent runs, tool calls) | 🟡 | Pydantic AI emits OTel spans; KAOS wraps with custom spans |
| R7.2 | OTel metrics (request count, duration, tool usage) | 🔴 | Must add custom metrics around Pydantic AI calls |
| R7.3 | W3C Trace Context propagation | 🟡 | Pydantic AI propagates; ensure KAOS delegation carries context |
| R7.4 | OTLP export configuration | 🔴 | Configure from OTEL_* env vars |
| R7.5 | User-facing `otel.enable()` utility | 🔴 | For custom image users |

## R8. Testing Infrastructure

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R8.1 | Mock model for unit tests (TestModel) | 🟡 | Pydantic AI has `TestModel`; need adapter for DEBUG_MOCK_RESPONSES format |
| R8.2 | DEBUG_MOCK_RESPONSES env var support for E2E | 🔴 | Custom model that reads env var and returns predetermined responses |
| R8.3 | Unit tests for agent creation/configuration | 🔴 | Test env var parsing, agent construction |
| R8.4 | Unit tests for agentic loop (tool calling, delegation) | 🔴 | Test tool execution, multi-step loops |
| R8.5 | Unit tests for memory bridge | 🔴 | Test Local/Redis/Null memory with Pydantic AI messages |
| R8.6 | Unit tests for server endpoints | 🔴 | Test HTTP API surface |
| R8.7 | E2E test compatibility | 🔴 | Ensure existing E2E tests pass with new framework |

## R9. Custom Image Support

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R9.1 | Standard wrapper mode (KAOS wraps user's Pydantic AI agent) | 🔴 | User provides agent definition, KAOS adds server/memory/telemetry |
| R9.2 | Template mode (user builds from KAOS base) | 🔴 | Dockerfile + template with KAOS utilities pre-configured |
| R9.3 | Utility functions (`kaos.enable_otel()`, `kaos.enable_memory()`, `kaos.serve()`) | 🔴 | Library functions for custom images |
| R9.4 | Agent CRD custom image support | 🟢 | Already exists via `spec.container.image` |

## R10. Build / Packaging

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R10.1 | Updated pyproject.toml with Pydantic AI dependencies | 🔴 | Add `pydantic-ai[mcp]`, `fasta2a` |
| R10.2 | Updated Dockerfile | 🔴 | Update CMD, dependencies |
| R10.3 | Updated Makefile (lint, test, format) | 🟡 | May need minor updates |
| R10.4 | CI pipeline compatibility | 🔴 | Ensure GitHub Actions workflows still pass |

## R11. Documentation

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| R11.1 | Update `.github/instructions/python.instructions.md` | 🔴 | Reflect new Pydantic AI architecture |
| R11.2 | Update `.github/instructions/e2e.instructions.md` | 🔴 | Update mock patterns if changed |
| R11.3 | Update `.github/copilot-instructions.md` | 🔴 | Update project overview |
| R11.4 | Update docs/ (VitePress) | 🔴 | Document new architecture |

---

## Feature Count Summary

| Category | Total | Native (🟢) | Partial (🟡) | Must Build (🔴) |
|----------|-------|-------------|--------------|-----------------|
| Core Agent | 7 | 3 | 2 | 2 |
| MCP Tools | 5 | 3 | 1 | 1 |
| Delegation | 4 | 0 | 0 | 4 |
| A2A Protocol | 4 | 3 | 0 | 1 |
| HTTP Server | 8 | 1 | 1 | 6 |
| Memory | 7 | 0 | 0 | 7 |
| Telemetry | 5 | 0 | 2 | 3 |
| Testing | 7 | 0 | 1 | 6 |
| Custom Images | 4 | 1 | 0 | 3 |
| Build/Packaging | 4 | 0 | 1 | 3 |
| Documentation | 4 | 0 | 0 | 4 |
| **TOTAL** | **59** | **11** | **8** | **40** |

---

*Roadmap version: 1.0*
*Based on KAOS v0.2.8-dev, Pydantic AI v0.2.x*
