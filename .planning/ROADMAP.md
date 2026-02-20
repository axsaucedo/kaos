# Roadmap: KAOS Python Framework Refactor

## Overview

This roadmap takes KAOS from its current custom Python data-plane through a structured evaluation of agentic AI frameworks, delivers framework-independent improvements (model fallback, structured outputs, OTel GenAI conventions), builds a Pydantic AI adapter as the recommended framework integration, adds A2A protocol compliance and MCP server capabilities, and validates the entire approach with production-representative testing. The journey is designed so that the first four phases deliver value regardless of the framework decision, while phases 5-8 execute the Pydantic AI hybrid adoption strategy validated by research.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Framework Evaluation & Decision** - Complete the comparison matrix, produce recommendation, define adapter contract
- [ ] **Phase 2: Model Routing Enhancement** - Add model fallback/failover with CRD-level configuration
- [ ] **Phase 3: Structured Output Validation** - Add Pydantic-based structured outputs with streaming support
- [ ] **Phase 4: OTel GenAI Conventions** - Align observability to GenAI semantic conventions while preserving backward compat
- [ ] **Phase 5: A2A Protocol Assessment** - Gap analysis of existing A2A endpoints against spec, verify backward compatibility
- [ ] **Phase 6: Pydantic AI Adapter Core** - Build kaos-adapter-pydanticai with env vars, memory bridge, OTel, and MCP support
- [ ] **Phase 7: A2A Protocol & MCP Server** - Add A2A protocol compliance via FastA2A and expose agents as MCP servers
- [ ] **Phase 8: Prototype & Validation** - Prototype a production agent and validate with tests, benchmarks, and migration guide

## Phase Details

### Phase 1: Framework Evaluation & Decision
**Goal**: The team has a clear, documented decision on which framework to adopt (or stay custom), with a defined adapter contract that de-risks all subsequent integration work
**Depends on**: Nothing (first phase)
**Requirements**: EVAL-01, EVAL-02, EVAL-03
**Success Criteria** (what must be TRUE):
  1. A comparison matrix exists covering all 9 frameworks across all evaluation dimensions (provider agnosticism, MCP, memory, OTel, A2A, extensibility, maturity) and a reader can compare any two frameworks at a glance
  2. A recommendation document exists with clear rationale that a developer unfamiliar with the project can read and understand why a specific framework was chosen (or why staying custom was chosen)
  3. An adapter contract specification exists defining required HTTP endpoints, env var mappings, memory interface, and OTel interface — any future framework adapter can be built against this contract
  4. The recommendation explicitly addresses every key concern from the ADK experience (A2A over-abstraction, cloud-locked memory, false provider agnosticism)
**Plans**: 5 plans

Plans:
- [ ] 01-01: Individual framework deep-dives (Pydantic AI, LangChain/LangGraph, CrewAI)
- [ ] 01-02: Individual framework deep-dives (Google ADK, AutoGen, Semantic Kernel)
- [ ] 01-03: Individual framework deep-dives (LlamaIndex, Haystack, DSPy)
- [ ] 01-04: Comparison matrix compilation and recommendation document
- [ ] 01-05: Adapter contract definition (endpoints, env vars, memory interface, OTel interface)

### Phase 2: Model Routing Enhancement
**Goal**: Users can configure model fallback so that agent requests automatically use a secondary model when the primary fails, with configuration surfaced in the CRD
**Depends on**: Phase 1 (adapter contract informs how model config flows)
**Requirements**: MODL-01, MODL-02
**Success Criteria** (what must be TRUE):
  1. When a user's primary model endpoint is unavailable or returns errors, the agent automatically retries with a configured fallback model — the user sees a successful response, not a 500 error
  2. Model fallback configuration is defined in the Agent CRD spec (not just environment variables), so users configure it declaratively alongside other agent settings
  3. Existing agents without fallback configuration continue to work identically (no regression)
**Plans**: 5 plans

Plans:
- [ ] 02-01: LiteLLM fallback configuration research and design
- [ ] 02-02: Implement model fallback/failover in Python agent runtime
- [ ] 02-03: CRD spec extension for model fallback configuration
- [ ] 02-04: Operator changes to propagate CRD fallback config to agent pods
- [ ] 02-05: Integration testing of fallback behavior end-to-end

### Phase 3: Structured Output Validation
**Goal**: Users can define Pydantic schemas for agent responses and get validated, structured output — including in streaming mode
**Depends on**: Phase 1 (adapter contract defines how structured outputs integrate)
**Requirements**: STRC-01, STRC-02, STRC-03
**Success Criteria** (what must be TRUE):
  1. A user can define a Pydantic model as the expected output schema for an agent, and the agent's response conforms to that schema
  2. When the model returns a response that doesn't match the schema, the agent rejects it and returns a clear validation error — not silently broken data
  3. Structured output validation works with streaming (SSE) responses — the user gets incremental streaming and still receives validated output at the end
  4. Agents that don't define an output schema continue to return free-form text responses as they do today
**Plans**: 5 plans

Plans:
- [ ] 03-01: Structured output schema definition mechanism design
- [ ] 03-02: Implement schema validation for non-streaming responses
- [ ] 03-03: Implement schema validation for streaming responses
- [ ] 03-04: Error handling and retry on validation failure
- [ ] 03-05: Integration testing across model providers

### Phase 4: OTel GenAI Conventions
**Goal**: KAOS OTel instrumentation follows GenAI semantic conventions so agent telemetry integrates cleanly with GenAI-aware observability tools, while existing telemetry continues working
**Depends on**: Nothing (can run in parallel with Phases 2-3)
**Requirements**: OTEL-01, OTEL-02
**Success Criteria** (what must be TRUE):
  1. OTel spans for model calls, tool calls, and agent runs use attribute names from the GenAI semantic conventions (e.g., `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`) — verifiable by inspecting exported spans in any OTel-compatible backend
  2. Existing OTel tracing, metrics, and log export to OTLP collectors continues to work without configuration changes — no regression for deployed agents
  3. A developer reading the telemetry code can identify which GenAI convention attributes are emitted for each operation type
**Plans**: 5 plans

Plans:
- [ ] 04-01: Audit current OTel attribute usage against GenAI semantic conventions
- [ ] 04-02: Update model call instrumentation to GenAI conventions
- [ ] 04-03: Update tool call and agent run instrumentation to GenAI conventions
- [ ] 04-04: Update metrics to GenAI conventions where applicable
- [ ] 04-05: Backward compatibility verification with existing OTel setup

### Phase 5: A2A Protocol Assessment
**Goal**: The team has a clear understanding of gaps between KAOS's current A2A implementation and the A2A protocol specification, and existing agent-to-agent delegation is verified as stable
**Depends on**: Phase 1 (framework decision affects A2A implementation approach)
**Requirements**: A2A-03, A2A-04
**Success Criteria** (what must be TRUE):
  1. A gap analysis document exists comparing the existing `/.well-known/agent` endpoint against the A2A spec's `/.well-known/agent.json` — listing every missing field, incompatible format, and required change
  2. Existing agent-to-agent delegation via `/v1/chat/completions` is explicitly tested and confirmed working (backward compatibility baseline before any A2A protocol changes)
  3. The gap analysis includes a concrete implementation plan with effort estimates for each gap — not just a list of differences
**Plans**: 5 plans

Plans:
- [ ] 05-01: A2A protocol specification review and requirement extraction
- [ ] 05-02: Current KAOS A2A endpoint audit (`/.well-known/agent`, delegation flow)
- [ ] 05-03: Gap analysis document (field-by-field comparison)
- [ ] 05-04: Backward compatibility test suite for existing delegation
- [ ] 05-05: Implementation plan for gap closure with effort estimates

### Phase 6: Pydantic AI Adapter Core
**Goal**: A working `kaos-adapter-pydanticai` package exists that reads KAOS env vars, creates a Pydantic AI Agent, bridges KAOS memory, preserves OTel observability, and integrates MCP tools
**Depends on**: Phase 1 (adapter contract), Phase 4 (OTel conventions)
**Requirements**: ADPT-01, ADPT-02, ADPT-03, ADPT-04
**Success Criteria** (what must be TRUE):
  1. A `kaos-adapter-pydanticai` package can be installed and, given KAOS env vars (model URL, MCP server URLs, memory config, OTel config), starts a FastAPI server that exposes `/v1/chat/completions` with the same interface as the current agent
  2. The adapter bridges KAOS RedisMemory to Pydantic AI's message history — a conversation across multiple requests in the same session maintains history, and history persists across pod restarts when using Redis
  3. OTel spans emitted by the adapter follow GenAI semantic conventions and appear in the same trace as KAOS infrastructure spans — a developer can see the full request lifecycle in one trace
  4. MCP tools configured via KAOS env vars are available to the Pydantic AI agent — the agent can discover and call MCP tools identically to the current implementation
  5. The adapter code is measurably simpler than the code it replaces — total lines of adapter code does not exceed 30% of the replaced agent code
**Plans**: 7 plans

Plans:
- [ ] 06-01: Package scaffolding and env var reader
- [ ] 06-02: Pydantic AI Agent creation from KAOS config
- [ ] 06-03: FastAPI wrapper with OpenAI-compatible endpoints
- [ ] 06-04: Memory bridge (RedisMemory ↔ Pydantic AI message_history)
- [ ] 06-05: OTel span integration and GenAI convention compliance
- [ ] 06-06: MCP tool integration via Pydantic AI native MCP support
- [ ] 06-07: Adapter integration testing (all components together)

### Phase 7: A2A Protocol & MCP Server
**Goal**: KAOS agents are A2A-protocol compliant and can be exposed as MCP servers, enabling discovery by IDEs and other agents via standard protocols
**Depends on**: Phase 5 (gap analysis), Phase 6 (adapter core)
**Requirements**: A2A-01, A2A-02, ADPT-05, MCPS-01, MCPS-02
**Success Criteria** (what must be TRUE):
  1. KAOS agent exposes `/.well-known/agent.json` endpoint that is fully compliant with the A2A protocol specification — an external A2A client can discover and interact with the agent using only the A2A protocol
  2. KAOS agent can consume remote agents via A2A protocol — agent-to-agent communication works using A2A (not just custom `/v1/chat/completions` delegation)
  3. The adapter uses FastA2A for A2A protocol compliance — not a custom A2A implementation
  4. KAOS agent can be exposed as an MCP server — an MCP-aware IDE (Cursor, VS Code + Copilot) can discover the agent's capabilities and send it requests
  5. MCP server exposure is configurable per agent via the CRD spec — not all agents are exposed as MCP servers by default
**Plans**: 6 plans

Plans:
- [ ] 07-01: FastA2A integration into adapter (A2A server side)
- [ ] 07-02: A2A-compliant discovery endpoint (`/.well-known/agent.json`)
- [ ] 07-03: A2A client for consuming remote agents
- [ ] 07-04: MCP server implementation for agent exposure
- [ ] 07-05: CRD spec extension for MCP server configuration
- [ ] 07-06: Protocol integration testing (A2A + MCP server end-to-end)

### Phase 8: Prototype & Validation
**Goal**: The Pydantic AI adapter is validated against a production-representative agent with passing tests, performance benchmarks, user impact assessment, and migration guide
**Depends on**: Phase 6 (adapter core), Phase 7 (A2A + MCP)
**Requirements**: ADPT-06, VALD-01, VALD-02, VALD-03, VALD-04, VALD-05
**Success Criteria** (what must be TRUE):
  1. At least one production-representative agent runs on the Pydantic AI adapter with all features working — memory, tools, A2A, streaming, OTel — and the team can demo it end-to-end
  2. Memory bridging assessment document exists showing exactly how KAOS MemoryEvents maps to Pydantic AI message_history, with identified gaps and their solutions
  3. User impact assessment and migration guide exists — a user currently building custom KAOS agent images can follow the guide to migrate to the Pydantic AI adapter
  4. All existing E2E tests pass with the adapter-based agent (or equivalent tests are created and pass)
  5. Performance benchmarks show the adapter-based agent is within acceptable bounds for cold start time and per-request latency compared to the custom agent (no more than 2x degradation)
**Plans**: 6 plans

Plans:
- [ ] 08-01: Production-representative agent prototype on adapter
- [ ] 08-02: Memory bridging assessment document (MemoryEvents ↔ message_history)
- [ ] 08-03: User impact assessment and migration guide
- [ ] 08-04: E2E test suite adaptation and execution
- [ ] 08-05: Performance benchmarking (cold start + per-request latency)
- [ ] 08-06: Go/no-go recommendation based on validation results

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

Note: Phases 2, 3, and 4 are framework-independent and can execute in parallel after Phase 1.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Framework Evaluation & Decision | 0/5 | Not started | - |
| 2. Model Routing Enhancement | 0/5 | Not started | - |
| 3. Structured Output Validation | 0/5 | Not started | - |
| 4. OTel GenAI Conventions | 0/5 | Not started | - |
| 5. A2A Protocol Assessment | 0/5 | Not started | - |
| 6. Pydantic AI Adapter Core | 0/7 | Not started | - |
| 7. A2A Protocol & MCP Server | 0/6 | Not started | - |
| 8. Prototype & Validation | 0/6 | Not started | - |
