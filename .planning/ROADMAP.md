# Roadmap: KAOS Exploratory Enhancement Initiative

## Overview

KAOS transforms from a functional-but-fragile agent framework into a production-grade Kubernetes-native AI agent orchestration platform. The roadmap addresses the #1 architectural gap (regex-based tool calling) first, then builds upward through persistent state, production hardening, protocol compliance, workflow orchestration, and developer experience — each phase delivering a coherent, verifiable capability that depends on what came before. Twelve phases cover 49 v1 requirements across tool calling, memory, guardrails, scaling, CRD hardening, protocol updates, workflows, evaluation, and DX.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Native Tool Calling & Structured Output** - Replace regex-based tool parsing with provider-native function calling and typed responses
- [ ] **Phase 2: MCP Connection Pooling** - Eliminate per-request connection overhead with persistent, health-checked MCP sessions
- [ ] **Phase 3: Persistent Memory & Session Management** - Make agent memory survive pod restarts with pluggable backends
- [ ] **Phase 4: Guardrails & Error Handling** - Add input/output validation hooks and resilient retry/circuit-breaker patterns
- [ ] **Phase 5: Autoscaling & Multi-Replica** - Enable horizontal scaling with HPA and custom OTel metrics
- [ ] **Phase 6: CRD Hardening & Webhooks** - Validate and default CRD fields at admission time with webhooks and CEL
- [ ] **Phase 7: Operator-Runtime Contract** - Lock down Go↔Python contract with shared schema and dependency pinning
- [ ] **Phase 8: Protocol Updates** - Migrate to official A2A SDK and align with latest MCP specification
- [ ] **Phase 9: Workflow Orchestration — Linear Pipelines** - Define and execute sequential multi-agent pipelines as CRDs
- [ ] **Phase 10: Workflow Orchestration — Parallel & Conditional** - Extend workflows with fan-out/fan-in, conditional routing, and durable execution
- [ ] **Phase 11: Evaluation Framework** - Enable deterministic replay testing with OTel-based assertions
- [ ] **Phase 12: PydanticAI Integration & Agent DX** - Add type-safe agent definitions, tool approval, and schema chaining

## Phase Details

### Phase 1: Native Tool Calling & Structured Output
**Goal**: Agents use reliable, provider-native function calling instead of fragile regex parsing, and can return typed Pydantic model responses
**Depends on**: Nothing (first phase)
**Requirements**: TOOL-01, TOOL-02, TOOL-03, TOOL-04, TOOL-05
**Success Criteria** (what must be TRUE):
  1. Agent invokes tools via the provider's native `tools` parameter and receives typed `tool_calls` in the response — no regex parsing involved for capable models
  2. Agent falls back to text-based tool parsing when connected to a model that doesn't support native function calling (e.g., Ollama-hosted models) — backward compatibility preserved
  3. Agent can return a response validated against a user-defined Pydantic model, not just a raw string
  4. When the provider returns multiple `tool_call` entries in a single response, the agent executes all of them (parallel tool calls work)
  5. `ModelResponse` object includes a typed `tool_calls` list with function name, arguments, and call ID accessible to the caller
**Plans:** 7 plans

Plans:
- [x] 01-01-PLAN.md — ModelAPI Foundation: ModelResponse & ToolCall types
- [x] 01-02-PLAN.md — CRD & Operator Plumbing (FunctionCalling field)
- [x] 01-03-PLAN.md — Agent Dual-Path Dispatch (native tool calling)
- [x] 01-04-PLAN.md — Streaming Tool Call Delta Accumulation
- [x] 01-05-PLAN.md — Mock System & Unit Tests Update
- [x] 01-06-PLAN.md — Operator Integration Tests & E2E Text Fallback
- [x] 01-07-PLAN.md — Text Parser Improvements & Documentation

### Phase 2: MCP Connection Pooling
**Goal**: MCP tool calls reuse persistent connections instead of paying TCP+TLS+MCP handshake costs on every invocation
**Depends on**: Nothing (parallelizable with Phase 1)
**Requirements**: MCP-01, MCP-02, MCP-03
**Success Criteria** (what must be TRUE):
  1. Consecutive MCP tool calls to the same server reuse an existing connection — no new TCP/TLS handshake per call
  2. Stale or broken MCP connections are detected by health checks and automatically replaced without caller intervention
  3. MCP connection pool initializes on FastAPI startup and cleanly shuts down on FastAPI shutdown — no leaked connections
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

### Phase 3: Persistent Memory & Session Management
**Goal**: Agent memory survives pod restarts using a pluggable backend system, with Redis as the production backend
**Depends on**: Nothing (can start after Phase 1, but no hard dependency)
**Requirements**: MEM-01, MEM-02, MEM-03, MEM-04, MEM-05, MEM-06
**Success Criteria** (what must be TRUE):
  1. Agent conversation history persists across pod restarts when using a persistent backend (Redis) — user continues where they left off after rescheduling
  2. `MemoryBackend` ABC exists and custom backend implementations can be plugged in by implementing the interface
  3. `LocalMemory` is the default for development; `RedisMemory` activates when CRD specifies `spec.memory.type: redis` — developer doesn't need Redis for local dev
  4. Sessions are isolated per conversation — one user's session doesn't leak into another's, even across pod restarts
  5. Memory entries expire based on TTL configuration — old sessions don't accumulate unboundedly in Redis
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

### Phase 4: Guardrails & Error Handling
**Goal**: Agents validate inputs before model invocation, validate outputs after, and handle LLM/tool failures gracefully with retries and circuit breakers
**Depends on**: Phase 1 (structured output enables typed output validation)
**Requirements**: GUARD-01, GUARD-02, GUARD-03, GUARD-04, GUARD-05
**Success Criteria** (what must be TRUE):
  1. A pre-execution hook can reject or transform a user prompt before it reaches the model — invalid/dangerous input is caught early
  2. A post-execution hook validates agent output against a Pydantic model or custom rules — malformed responses are caught before reaching the caller
  3. Transient LLM API failures are retried with exponential backoff without manual intervention — agents recover from temporary provider outages
  4. MCP/A2A tool call failures trigger retries with circuit breaker protection — a persistently failing tool doesn't cascade into infinite retry loops
  5. When a tool call fails, the agent receives a structured error it can reason about (not an unhandled exception) — the agent can decide to retry, skip, or report
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

### Phase 5: Autoscaling & Multi-Replica
**Goal**: Agents scale horizontally based on load, with CRD-driven configuration and safety guardrails against data loss
**Depends on**: Phase 3 (persistent memory required — multi-replica with in-memory state is broken by design)
**Requirements**: SCALE-01, SCALE-02, SCALE-03, SCALE-04
**Success Criteria** (what must be TRUE):
  1. Setting `spec.replicas: 3` in the Agent CRD results in 3 running pods for that agent
  2. Operator creates an HPA resource that scales agent pods based on CPU utilization and custom OTel metrics (request rate, latency)
  3. CRD validation rejects `replicas > 1` when `memory.type` is `local` — the system prevents data-loss misconfigurations
  4. Agent pods expose OTel metrics (request rate, queue depth, latency) that an HPA custom metrics adapter can consume
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

### Phase 6: CRD Hardening & Webhooks
**Goal**: CRD fields are validated at admission time via webhooks and CEL expressions — misconfigurations are rejected before they reach the reconciler
**Depends on**: Phases 1-5 (CRD schema stabilized after all new fields added)
**Requirements**: CRD-01, CRD-02, CRD-03, CRD-04
**Success Criteria** (what must be TRUE):
  1. Submitting an Agent CRD referencing a non-existent ModelAPI is rejected at admission time with a clear error — not silently accepted then broken at runtime
  2. Submitting an Agent CRD with missing optional fields results in intelligent defaults being applied (mutating webhook) — users don't need to specify every field
  3. Simple field constraints (enum values, numeric ranges) are enforced via CEL expressions in the CRD schema — no webhook round-trip needed for basic validation
  4. Webhook deployment is optional in the Helm chart — disabled by default, enabled via `values.yaml` — clusters without cert-manager can still run KAOS
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD

### Phase 7: Operator-Runtime Contract
**Goal**: The Go operator and Python runtime share a verified contract for environment variables and dependencies, preventing silent configuration drift
**Depends on**: Phases 1-6 (contract codifies all env vars accumulated across prior phases)
**Requirements**: CONTRACT-01, CONTRACT-02, CONTRACT-03, CONTRACT-04, CONTRACT-05
**Success Criteria** (what must be TRUE):
  1. A JSON schema file exists that defines every env var the operator passes to the runtime — the contract is explicit, not implicit
  2. Go tests verify that `constructEnvVars` output matches the contract schema — adding an env var in Go without updating the contract fails CI
  3. Python tests verify that `AgentServerSettings` fields match the contract schema — reading an env var in Python without it being in the contract fails CI
  4. Critical Python dependencies (pydantic, fastapi, litellm, fastmcp) have upper-bound version constraints — a surprise major version bump doesn't break production
  5. CI enforces lockfile consistency — `poetry.lock` or `uv.lock` is checked in and validated on every build
**Plans**: TBD

Plans:
- [ ] 07-01: TBD
- [ ] 07-02: TBD

### Phase 8: Protocol Updates
**Goal**: A2A implementation uses the official SDK and agents expose Agent Cards; MCP client aligns with the latest specification
**Depends on**: Phase 7 (contract locked down before protocol changes add new interfaces)
**Requirements**: PROTO-01, PROTO-02, PROTO-03, PROTO-04
**Success Criteria** (what must be TRUE):
  1. Custom A2A implementation is replaced by the official `a2a-sdk` library — KAOS tracks the Linux Foundation standard instead of maintaining bespoke protocol code
  2. Every agent exposes an Agent Card at `/.well-known/agent.json` per the A2A spec — external agents can discover KAOS agent capabilities programmatically
  3. MCP client supports the 2025-11-25 MCP specification features (Tasks capability, Elicitation where applicable) — KAOS is current with the MCP ecosystem
  4. A2A inter-agent communication supports SSE streaming and async push for long-running tasks — agents don't block on slow peers
**Plans**: TBD

Plans:
- [ ] 08-01: TBD
- [ ] 08-02: TBD

### Phase 9: Workflow Orchestration — Linear Pipelines
**Goal**: Users can define sequential multi-agent pipelines as Kubernetes CRDs and execute them through the data plane
**Depends on**: Phase 8 (workflows use A2A for inter-agent steps; official SDK should be in place first)
**Requirements**: WFLOW-01, WFLOW-02, WFLOW-03, WFLOW-04
**Success Criteria** (what must be TRUE):
  1. A new `AgentWorkflow` CRD allows users to define a sequential pipeline (Agent A → Agent B → Agent C) declaratively in YAML
  2. The workflow executor runs in the Python data plane, not the Go operator reconciler — the reconciler manages Deployments/HTTPRoutes, the runtime manages request execution
  3. Each step's output is available to subsequent steps via template interpolation — downstream agents receive context from upstream
  4. Applying an `AgentWorkflow` CRD results in the operator creating the necessary Deployment and HTTPRoute resources for the workflow endpoint
**Plans**: TBD

Plans:
- [ ] 09-01: TBD
- [ ] 09-02: TBD

### Phase 10: Workflow Orchestration — Parallel & Conditional
**Goal**: Workflows support parallel fan-out/fan-in, conditional routing, and durable checkpoint-based execution
**Depends on**: Phase 9 (extends linear pipeline foundation with DAG execution)
**Requirements**: WFLOW-05, WFLOW-06, WFLOW-07
**Success Criteria** (what must be TRUE):
  1. Workflow steps can execute in parallel via `dependsOn` DAG edges — independent steps run concurrently, dependent steps wait
  2. Workflow steps can be conditionally skipped or routed based on the output of a previous step — not all paths must execute
  3. Workflow execution checkpoints progress after each step — an interrupted workflow can resume from the last completed step, not restart from scratch
**Plans**: TBD

Plans:
- [ ] 10-01: TBD
- [ ] 10-02: TBD

### Phase 11: Evaluation Framework
**Goal**: Developers can write deterministic replay tests for agents using YAML scenario files and OTel-based assertions
**Depends on**: Phase 1 (structured output), Phase 3 (persistent memory for stateful tests)
**Requirements**: EVAL-01, EVAL-02, EVAL-03
**Success Criteria** (what must be TRUE):
  1. Developer can mock LLM responses and verify that the agent made the expected tool calls and produced the expected output — deterministic replay testing works
  2. Eval scenarios are defined in YAML files — no Python test code needed to define what to test, only how to assert
  3. Eval framework uses `InMemorySpanExporter` from existing OTel instrumentation for assertions on agent behavior — no separate telemetry infrastructure needed for testing
**Plans**: TBD

Plans:
- [ ] 11-01: TBD

### Phase 12: PydanticAI Integration & Agent DX
**Goal**: Developers can define agents using PydanticAI's type-safe patterns with dependency injection, tool approval, and schema-chained pipelines
**Depends on**: Phases 1-11 (DX layer on top of working infrastructure)
**Requirements**: DX-01, DX-02, DX-03
**Success Criteria** (what must be TRUE):
  1. A PydanticAI-based agent definition works as an alternative to the current agent pattern — type-safe agents with dependency injection are supported
  2. Agents support a human-in-the-loop tool approval pattern — sensitive tool calls can be paused for approval before execution
  3. Pipeline composition validates that output type of Agent A matches input type of Agent B at definition time — type mismatches are caught before runtime
**Plans**: TBD

Plans:
- [ ] 12-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

Note: Phases 1 and 2 are parallelizable (no dependency between them).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Native Tool Calling & Structured Output | 7/7 | ✅ Complete | 2026-02-14 |
| 2. MCP Connection Pooling | 0/TBD | Not started | - |
| 3. Persistent Memory & Session Management | 0/TBD | Not started | - |
| 4. Guardrails & Error Handling | 0/TBD | Not started | - |
| 5. Autoscaling & Multi-Replica | 0/TBD | Not started | - |
| 6. CRD Hardening & Webhooks | 0/TBD | Not started | - |
| 7. Operator-Runtime Contract | 0/TBD | Not started | - |
| 8. Protocol Updates | 0/TBD | Not started | - |
| 9. Workflow — Linear Pipelines | 0/TBD | Not started | - |
| 10. Workflow — Parallel & Conditional | 0/TBD | Not started | - |
| 11. Evaluation Framework | 0/TBD | Not started | - |
| 12. PydanticAI Integration & Agent DX | 0/TBD | Not started | - |

---
*Roadmap created: 2026-02-13*
*Last updated: 2026-02-14 — Phase 1 complete*
