# KAOS Pydantic AI Integration — Implementation Plan

## Approach

Replace the custom Python agent framework (`data-plane/kaos-framework/`) with Pydantic AI in an incremental, test-driven manner. Each task is a self-contained commit with passing tests.

**Guiding principles:**
- Preserve the operator env-var contract (no Go operator changes)
- Preserve the HTTP API surface for backward compatibility
- Keep memory system (Local/Redis/Null) since Pydantic AI has no built-in persistence
- All unit tests pass after each task; E2E tests validated via CI PR
- Breaking changes are acceptable (alpha stage); no migration docs required

## Process & Quality Gates

Each task MUST follow this workflow:

1. **Implement** the task changes
2. **Run tests locally** — `python -m pytest tests/ -v` + `make lint` must pass
3. **Commit** with comprehensive conventional commit style (succinct, functional descriptions)
4. **Push to PR** — create PR if not exists; push after each commit or batch of related commits
5. **Validate CI** — monitor GitHub Actions; all workflows must pass
6. **For major refactors** — also run Go operator tests locally (`cd operator && make test-unit`)
7. **For E2E-impacting changes** — run 1-3 E2E tests locally via KIND cluster before pushing full suite to CI
8. **If CI fails** — run 1-3 failing tests locally to diagnose, fix, re-push

**CI preference:** Run the complete test suite in GitHub Actions CI. Only run locally when CI fails or for pre-validation of major changes.

**Final deliverable:** After all tasks complete, create `REPORT.md` (gitignored) with a thorough overview of all requested tasks and their completion status.

---

## Implementation Tasks

### Task 1: Project setup — Add Pydantic AI dependencies

**Scope:** Update `pyproject.toml` to add `pydantic-ai[mcp]` and `fasta2a`. Remove `litellm` and `fastmcp` (replaced by Pydantic AI). Update the virtual environment. Verify existing tests still run (they will fail — that's expected after Task 2+).

**Files:** `pyproject.toml`, `Makefile` (if needed)

**Validation:** `pip install -e ".[dev]"` succeeds, `python -c "import pydantic_ai"` works.

---

### Task 2: Core agent — Replace Agent class with Pydantic AI Agent

**Scope:** Rewrite `agent/client.py`:
- Replace custom `Agent` class with a thin wrapper around `pydantic_ai.Agent`
- Configure model via `OpenAIModel(provider=OpenAIProvider(base_url=MODEL_API_URL))`
- Support system prompt configuration
- Support `max_result_retries` for loop control
- Keep `AgentCard` dataclass for A2A discovery
- Remove `RemoteAgent` (will be re-implemented as delegation tools in Task 4)
- Remove custom agentic loop, tool calling modes, `ToolCall`/`ModelResponse` dataclasses

**Files:** `agent/client.py`

**Validation:** Basic unit test — create agent, verify configuration, run with TestModel.

---

### Task 3: MCP integration — Wire MCP servers to Pydantic AI

**Scope:** Replace `mcptools/client.py` with env-var parsing that creates `pydantic_ai.mcp.MCPServerHTTP` instances. Parse `MCP_SERVERS` and `MCP_SERVER_<name>_URL` env vars.

**Files:** `mcptools/client.py` (rewrite or remove), `agent/client.py` (accept MCP servers)

**Validation:** Unit test — verify MCPServerHTTP instances created from env vars.

---

### Task 4: Sub-agent delegation — Implement delegation as Pydantic AI tools

**Scope:** Implement delegation to peer agents as Pydantic AI tool functions:
- Parse `PEER_AGENTS` + `PEER_AGENT_<name>_CARD_URL` env vars
- Fetch agent cards from `/.well-known/agent.json` endpoints
- Create `delegate_to_{name}` tool functions on the Pydantic AI Agent
- Use A2A protocol (tasks/send via httpx) for communication
- Handle unavailable agents (skip at startup)

**Files:** `agent/client.py` (delegation tools), new `agent/delegation.py` if needed

**Validation:** Unit test — delegation tool creation, mock A2A call.

---

### Task 5: Memory bridge — Connect KAOS memory to Pydantic AI message history

**Scope:** Bridge Pydantic AI's `message_history` (list of `ModelRequest`/`ModelResponse`) to KAOS memory events:
- Keep `MemoryEvent`, `SessionMemory` dataclasses
- Keep `LocalMemory`, `RedisMemory`, `NullMemory` implementations
- Add conversion functions: Pydantic AI messages → KAOS events and vice versa
- On agent.run(), load message_history from KAOS memory, run agent, store new messages back

**Files:** `agent/memory.py` (adapt), new `agent/memory_bridge.py` if needed

**Validation:** Unit tests — round-trip conversion, LocalMemory storage/retrieval, NullMemory no-op.

---

### Task 6: Mock model — Implement DEBUG_MOCK_RESPONSES for Pydantic AI

**Scope:** Create a custom Pydantic AI model (or `FunctionModel`) that reads `DEBUG_MOCK_RESPONSES` env var and returns predetermined responses in sequence. Must support:
- Plain text responses
- Tool call responses (same JSON format as current)
- Per-request isolation (contextvars or similar)

**Files:** New `agent/mock_model.py` or within `agent/client.py`

**Validation:** Unit test — mock model returns expected sequence, tool calls parsed correctly.

---

### Task 7: HTTP server — Rewrite server with Pydantic AI + health/memory endpoints

**Scope:** Rewrite `agent/server.py`:
- Keep `AgentServerSettings` (pydantic BaseSettings for env var reading)
- Mount health endpoints: `GET /health`, `GET /ready`
- Mount memory endpoints: `GET /memory/events`, `GET /memory/sessions`
- Mount A2A app via `agent.to_a2a()` (provides `/.well-known/agent.json`, task endpoints)
- Mount backward-compatible `POST /v1/chat/completions` (wraps Pydantic AI agent.run)
- Keep session ID handling (X-Session-ID header)
- Keep `create_agent_server()` factory pattern

**Files:** `agent/server.py`

**Validation:** Unit tests — endpoint responses, health checks, settings parsing.

---

### Task 8: Telemetry integration — Wire OTel to Pydantic AI

**Scope:** Adapt `telemetry/manager.py`:
- Configure Pydantic AI to use KAOS OTel tracer provider (not Logfire)
- Keep custom metrics (request count, duration, tool usage)
- Ensure W3C Trace Context propagation in delegation calls
- Provide `otel.enable()` utility for custom image users

**Files:** `telemetry/manager.py` (adapt)

**Validation:** Unit tests — span creation, metric recording.

---

### Task 9: Comprehensive unit tests — Full test suite

**Scope:** Rewrite test files to cover the new Pydantic AI-based framework:
- `test_agent.py`: Agent creation, configuration, basic run
- `test_agentic_loop.py`: Tool calling, delegation, max steps, streaming
- `test_memory.py`: Memory bridge, all three backends
- `test_server.py`: HTTP endpoints, streaming, session handling
- Ensure `make lint` passes (black + ty check)

**Files:** `tests/test_agent.py`, `tests/test_agentic_loop.py`, `tests/test_agent_server.py`

**Validation:** `python -m pytest tests/ -v` — all pass. `make lint` — clean.

---

### Task 10: Dockerfile and build — Update container image

**Scope:** Update Dockerfile for new dependencies:
- Update `pip install` for pydantic-ai
- Update CMD if entrypoint changes
- Verify health probes still work with new server

**Files:** `Dockerfile`

**Validation:** `docker build .` succeeds.

---

### Task 11: E2E test compatibility — Validate with KIND cluster

**Scope:** Run E2E tests against the new framework:
- Build and load new images into KIND
- Run 1-3 E2E tests locally to validate
- Push to CI for full E2E suite
- Fix any integration issues

**Files:** Potentially `operator/tests/e2e/` (if mock format changes)

**Validation:** E2E tests pass in CI.

---

### Task 12: Documentation updates

**Scope:** Update all relevant documentation:
- `.github/instructions/python.instructions.md` — new architecture, patterns, env vars
- `.github/instructions/e2e.instructions.md` — updated mock patterns if needed
- `.github/copilot-instructions.md` — project overview update
- `docs/` VitePress content if applicable

**Files:** `.github/instructions/*.md`, `.github/copilot-instructions.md`

**Validation:** Documentation is accurate and reflects new codebase.

---

## Deferred to Follow-up Implementation

The following features from the ROADMAP are **not included** in this initial delivery:

| Feature | Reason for Deferral |
|---------|-------------------|
| R1.5 String-mode tool calling | Pydantic AI auto-detects; can add custom model wrapper later if needed |
| R7.2 Custom OTel metrics (counters, histograms) | Basic tracing first; metrics in follow-up |
| R7.3 W3C Trace Context in delegation | Tracing spans first; distributed context later |
| R9.1 Standard wrapper mode (KAOS wraps user's agent) | Core framework first; custom image UX later |
| R9.2 Template mode | Core framework first |
| R9.3 Utility functions (kaos.enable_*) | Core framework first |
| R11.4 VitePress docs update | After framework stabilizes |

---

## Task Dependency Graph

```
Task 1 (deps)
  └─► Task 2 (core agent)
       ├─► Task 3 (MCP)
       ├─► Task 4 (delegation)
       ├─► Task 5 (memory bridge)
       └─► Task 6 (mock model)
            └─► Task 7 (HTTP server)
                 └─► Task 8 (telemetry)
                      └─► Task 9 (full tests)
                           └─► Task 10 (Dockerfile)
                                └─► Task 11 (E2E)
                                     └─► Task 12 (docs)
```

---

## Commit Strategy

Each task = one conventional commit:
- Task 1: `feat(framework): add pydantic-ai dependencies`
- Task 2: `feat(framework): replace agent core with pydantic-ai`
- Task 3: `feat(framework): integrate mcp via pydantic-ai native support`
- Task 4: `feat(framework): implement sub-agent delegation as pydantic-ai tools`
- Task 5: `feat(framework): bridge kaos memory to pydantic-ai message history`
- Task 6: `feat(framework): implement debug mock model for pydantic-ai`
- Task 7: `feat(framework): rewrite http server with pydantic-ai and fasta2a`
- Task 8: `feat(framework): integrate otel telemetry with pydantic-ai`
- Task 9: `test(framework): comprehensive unit test suite for pydantic-ai`
- Task 10: `build(framework): update dockerfile for pydantic-ai`
- Task 11: `test(e2e): validate pydantic-ai framework with kind cluster`
- Task 12: `docs: update instructions for pydantic-ai framework`

---

## Final Report

After all 12 tasks are complete, create `REPORT.md` (gitignored) documenting:
- All tasks requested (including research documents, roadmap, plan creation)
- Implementation task completion status (pass/fail, CI results)
- Any issues encountered and resolutions
- Deferred items and rationale

---

*Plan version: 1.1*
*Estimated tasks: 12 implementation + 3 pre-work (research, roadmap, plan)*
*Deferred features: 7 (from 59 total in ROADMAP)*
