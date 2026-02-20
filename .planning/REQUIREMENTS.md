# Requirements: KAOS Python Framework Refactor

**Defined:** 2026-02-20
**Core Value:** Identify and adopt the best agentic AI framework foundation for KAOS's Python data-plane — provider-agnostic, K8s-native, with distributed memory, observability, and flexible A2A communication.

## v1 Requirements

Requirements for the framework evaluation and initial adoption. Each maps to roadmap phases.

### Framework Evaluation

- [ ] **EVAL-01**: Complete framework comparison matrix covering all 9 frameworks (Pydantic AI, LangChain/LangGraph, CrewAI, Google ADK, AutoGen, Semantic Kernel, LlamaIndex, Haystack, DSPy) across provider agnosticism, MCP, memory, OTel, A2A, extensibility, and maturity
- [ ] **EVAL-02**: Produce written recommendation document with clear rationale for which framework to adopt (or confirm staying custom)
- [ ] **EVAL-03**: Define adapter contract specifying required endpoints, env var mapping, memory interface, and OTel interface that any framework integration must satisfy

### Model Routing

- [ ] **MODL-01**: User can configure model fallback/failover so that if the primary model fails, a secondary model is used automatically
- [ ] **MODL-02**: Model fallback configuration is surfaced via Agent CRD spec (not just env vars)

### Structured Outputs

- [ ] **STRC-01**: User can define structured output schemas for agent responses using Pydantic models
- [ ] **STRC-02**: Agent validates responses against the defined schema before returning to the caller
- [ ] **STRC-03**: Structured output validation works with streaming responses

### A2A Protocol

- [ ] **A2A-01**: Agent exposes A2A-compliant discovery endpoint (`/.well-known/agent.json`) per the A2A protocol specification
- [ ] **A2A-02**: Agent can consume remote agents via A2A protocol (not just custom `/v1/chat/completions` delegation)
- [ ] **A2A-03**: A2A endpoint alignment assessed — existing `/.well-known/agent` mapped to A2A spec requirements with gap analysis
- [ ] **A2A-04**: Existing agent-to-agent delegation continues to work (backward compatible)

### MCP Server

- [ ] **MCPS-01**: KAOS agent can be exposed as an MCP server, allowing IDEs and other MCP-aware tools to discover and call the agent
- [ ] **MCPS-02**: MCP server exposure is configurable per agent via CRD spec

### Observability

- [ ] **OTEL-01**: OTel instrumentation follows GenAI semantic conventions for attribute names on AI operations (model calls, tool calls, agent runs)
- [ ] **OTEL-02**: Existing OTel tracing, metrics, and log export continue to work (backward compatible)

### Pydantic AI Adapter

- [ ] **ADPT-01**: Build `kaos-adapter-pydanticai` package that reads KAOS env vars, creates a Pydantic AI Agent, wraps with FastAPI, and exposes all required KAOS endpoints
- [ ] **ADPT-02**: Adapter bridges KAOS memory (RedisMemory) to Pydantic AI's message history pattern
- [ ] **ADPT-03**: Adapter preserves OTel observability (spans, metrics, log correlation)
- [ ] **ADPT-04**: Adapter supports MCP tool integration via Pydantic AI's native MCP support
- [ ] **ADPT-05**: Adapter supports A2A communication using FastA2A
- [ ] **ADPT-06**: At least one production-representative agent is prototyped using the adapter

### Validation

- [ ] **VALD-01**: Memory bridging assessment completed — documented how KAOS MemoryEvents maps to Pydantic AI message_history, with identified gaps and solutions
- [ ] **VALD-02**: User impact assessment completed — documented how the framework change affects users building custom KAOS agent images, with migration guide
- [ ] **VALD-03**: All existing E2E tests pass with the adapter-based agent (or equivalents created)
- [ ] **VALD-04**: All existing examples updated or equivalent examples provided for the new framework
- [ ] **VALD-05**: Performance validation — adapter-based agent benchmarked against custom agent for cold start and per-request latency

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Semantic Memory

- **SMEM-01**: Agent can store and retrieve long-term knowledge across sessions using semantic search
- **SMEM-02**: Semantic memory supports Redis or PostgreSQL as backend

### Durable Execution

- **DURX-01**: Agent workflows can resume after pod restart or failure
- **DURX-02**: Durable execution state persists to external storage

### Advanced Streaming

- **STRM-01**: Bidirectional streaming for audio/video use cases
- **STRM-02**: Streaming with concurrent tool execution

### DSPy Integration

- **DSPY-01**: Users can optionally use DSPy modules for prompt optimization within KAOS agents
- **DSPY-02**: DSPy integration documented with examples

## Out of Scope

| Feature | Reason |
|---------|--------|
| CRD `spec.framework` field for multi-framework support | Plan is to pick one framework and support it excellently, not support every framework |
| Proprietary observability (LangSmith, Logfire) | Violates open-standards philosophy; OTel is the standard |
| Cloud-locked memory (Vertex AI, Azure) | KAOS runs anywhere; no cloud vendor lock-in |
| No-code visual builder | Massive effort, low alignment with developer-tool positioning |
| Graph-based state machines (LangGraph-style) | Adds complexity; KAOS's simple tool loop is a feature |
| Role/persona-based agent definition (CrewAI-style) | Over-abstraction; agents defined by tools + instructions |
| Multi-language SDKs | Engineering cost too high; OpenAI-compatible API means any language can consume KAOS agents |
| Google ADK adoption | GCP/Vertex lock-in confirmed; rejected by team experience |
| LangChain/LangGraph adoption | Over-abstraction, LangSmith lock-in, dependency bloat |
| CrewAI, AutoGen, Haystack adoption | Paradigm mismatch, runtime conflicts, or insufficient value |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| EVAL-01 | Phase 1 | Pending |
| EVAL-02 | Phase 1 | Pending |
| EVAL-03 | Phase 1 | Pending |
| MODL-01 | Phase 2 | Pending |
| MODL-02 | Phase 2 | Pending |
| STRC-01 | Phase 2 | Pending |
| STRC-02 | Phase 2 | Pending |
| STRC-03 | Phase 2 | Pending |
| A2A-01 | Phase 3 | Pending |
| A2A-02 | Phase 3 | Pending |
| A2A-03 | Phase 3 | Pending |
| A2A-04 | Phase 3 | Pending |
| MCPS-01 | Phase 3 | Pending |
| MCPS-02 | Phase 3 | Pending |
| OTEL-01 | Phase 2 | Pending |
| OTEL-02 | Phase 2 | Pending |
| ADPT-01 | Phase 3 | Pending |
| ADPT-02 | Phase 3 | Pending |
| ADPT-03 | Phase 3 | Pending |
| ADPT-04 | Phase 3 | Pending |
| ADPT-05 | Phase 3 | Pending |
| ADPT-06 | Phase 3 | Pending |
| VALD-01 | Phase 4 | Pending |
| VALD-02 | Phase 4 | Pending |
| VALD-03 | Phase 4 | Pending |
| VALD-04 | Phase 4 | Pending |
| VALD-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-20*
*Last updated: 2026-02-20 after initial definition*
