# KAOS Pydantic AI Integration — Final Report

## Overview

Complete rewrite of the KAOS data-plane Python agent framework (`data-plane/kaos-framework/`) to use **Pydantic AI** as the first-class agent framework, replacing the custom implementation built on litellm/fastmcp.

**PR:** [#88](https://github.com/axsaucedo/kaos/pull/88)
**Branch:** `feat/exploration-pydantic-ai`

---

## Pre-Implementation Tasks

| Task | Status | Output |
|------|--------|--------|
| Codebase research | ✅ Done | `REPORT-RESEARCH.md` — full analysis of existing codebase, Pydantic AI capabilities, gap analysis |
| Feature roadmap | ✅ Done | `ROADMAP.md` — 59 features across 11 categories (11 native, 8 partial, 40 to build) |
| Implementation plan | ✅ Done | `PLAN.md` — 12 tasks with dependency graph, process instructions, deferred items |

---

## Implementation Tasks

| # | Task | Status | Commit | Notes |
|---|------|--------|--------|-------|
| 1 | Add Pydantic AI dependencies | ✅ Done | `e8e26a2` | Replaced litellm/fastmcp with pydantic-ai/fasta2a |
| 2 | Replace Agent core with Pydantic AI | ✅ Done | `c544569` | Complete rewrite of client.py wrapping pydantic_ai.Agent |
| 3 | MCP integration | ✅ Done | (part of Task 2) | MCPServerStreamableHTTP via toolsets parameter |
| 4 | Sub-agent delegation | ✅ Done | (part of Task 2) | delegate_to_ tool functions registered on Pydantic AI Agent |
| 5 | Memory bridge | ✅ Done | (part of Task 2) | KAOS events ↔ Pydantic AI ModelRequest/ModelResponse conversion |
| 6 | Mock model | ✅ Done | (part of Task 2) | FunctionModel with _MockResponseState (ContextVar workaround) |
| 7 | HTTP server rewrite | ✅ Done | `c544569` | FastAPI with health/memory/chat/A2A endpoints |
| 8 | Telemetry integration | ✅ Done | `c544569` | OTel spans for process_message, tool calls, delegation |
| 9 | Comprehensive unit tests | ✅ Done | `c544569` | 69 tests pass, 10 skipped (server integration needing Ollama) |
| 10 | Dockerfile update | ✅ Done | `fdbd11e` | Removed mcptools/modelapi COPY steps |
| 11 | E2E validation | ✅ Done | `e103a36` | All E2E suites pass: agentic-loop (5/5), MCP (6/6), multi-agent (3/3) |
| 12 | Documentation | ✅ Done | `1051944` | Updated python.instructions.md, e2e.instructions.md, copilot-instructions.md |

---

## Key Technical Decisions

### Why Pydantic AI
- ADK rejected: extreme GCP/Vertex lock-in (distributed memory only via Vertex)
- LangFuse/CrewAI rejected: overcomplicated for KAOS's Kubernetes-native use case
- Pydantic AI: clean API, native MCP support, OpenAI-compatible, no cloud vendor lock-in

### Architecture
- `Agent` wraps `pydantic_ai.Agent` — KAOS handles env-var config, memory, delegation registration
- MCP via `MCPServerStreamableHTTP` (native Pydantic AI support)
- Delegation as `@agent.tool_plain` functions with `delegate_to_` prefix
- No custom agentic loop — Pydantic AI handles tool calling natively
- Memory bridge: bidirectional conversion between KAOS events and Pydantic AI messages

### Breaking Changes (acceptable — alpha stage)
- **Removed `TOOL_CALL_MODE`** — Pydantic AI uses native tool calling only (no string mode)
- **Removed `mcptools/` and `modelapi/` modules** — replaced by Pydantic AI native support
- **Mock responses need 2 entries** (not 3) for tool calls — legacy 3-entry format still works
- **Removed `ToolCall`/`ModelResponse` dataclasses** — Pydantic AI provides its own message types

### Issues Encountered & Resolved

1. **ContextVar + FunctionModel**: Pydantic AI copies context for each FunctionModel call, breaking ContextVar state. Fixed with `_MockResponseState` class (mutable closure).
2. **MCP URL path**: FastMCP serves at `/mcp` endpoint. Added URL path suffix in server.py.
3. **Delegation memory events**: `delegate_to_*` calls must be stored as `delegation_request`/`delegation_response` (not `tool_call`/`tool_result`) for E2E assertions.
4. **Task delegation detection**: Incoming `task-delegation` role must be stored as `task_delegation_received` event.
5. **Agent card skills**: Must discover tools from MCP servers via `list_tools()` on card requests.
6. **`model_config` Pydantic v2**: Pydantic v2 requires `model_config = {}` dict, not `class Config:`.

---

## Test Results

### Unit Tests
- **69 passed**, 10 skipped (server integration tests requiring Ollama)
- Lint: clean (black + ty check)

### E2E Tests (local KIND cluster)
- Agentic loop: **5/5 passed**
- MCP tools: **6/6 passed**
- Multi-agent: **3/3 passed**

### CI
- Python unit tests pass in CI
- E2E tests in CI affected by pre-existing `kind-registry` infrastructure issue (not related to our changes)

---

## Deferred to Follow-up

| Feature | Reason |
|---------|--------|
| R1.5 String-mode tool calling | Pydantic AI auto-detects; no longer needed |
| R7.2 Custom OTel metrics | Basic tracing implemented; detailed metrics later |
| R7.3 W3C Trace Context in delegation | Tracing spans done; distributed context propagation later |
| R9.1 Standard wrapper mode | Core framework first; custom image UX later |
| R9.2 Template mode | Core framework first |
| R9.3 Utility functions (kaos.enable_*) | Core framework first |
| R11.4 VitePress docs update | After framework stabilizes |

---

## Commits (chronological)

1. `e8e26a2` — `feat(framework): add pydantic-ai dependencies and research documents`
2. `c544569` — `feat(framework): replace agent core with pydantic-ai`
3. `8f9b07c` — `fix(framework): use model_config dict for pydantic v2 settings`
4. `fdbd11e` — `build(framework): update dockerfile for pydantic-ai`
5. `e103a36` — `test(e2e): validate pydantic-ai framework with kind cluster`
6. `1051944` — `docs: update instructions for pydantic-ai framework`

---

## Files Changed

### New Files
- `REPORT-RESEARCH.md` — Codebase analysis and Pydantic AI evaluation
- `ROADMAP.md` — Feature roadmap (59 features)
- `PLAN.md` — Implementation plan (12 tasks)
- `REPORT.md` — This report

### Modified Files
- `data-plane/kaos-framework/pyproject.toml` — Dependencies
- `data-plane/kaos-framework/agent/client.py` — Complete rewrite (~490 lines)
- `data-plane/kaos-framework/agent/server.py` — Updated imports, MCP URLs, model_config
- `data-plane/kaos-framework/tests/test_agent.py` — Complete rewrite (23 tests)
- `data-plane/kaos-framework/tests/test_agentic_loop.py` — Complete rewrite (29 tests)
- `data-plane/kaos-framework/Dockerfile` — Removed mcptools/modelapi
- `operator/tests/e2e/test_mcp_tools_e2e.py` — Updated string-mode test to tool_calls format
- `.github/instructions/python.instructions.md` — New Pydantic AI architecture docs
- `.github/instructions/e2e.instructions.md` — Updated mock patterns
- `.github/copilot-instructions.md` — Updated project structure and key files
