# Project Research Summary

**Project:** KAOS — Kubernetes-Native Agent Orchestration Platform
**Domain:** Agentic AI Framework Evaluation (Python Data-Plane)
**Researched:** 2026-02-20
**Confidence:** HIGH

## Executive Summary

KAOS is a Kubernetes-native agent orchestration platform with a Go operator (control plane) and Python agent runtime (data plane). The team evaluated 9 leading agentic AI frameworks to determine whether any should replace or augment the custom Python data-plane code. The research is unambiguous: **Pydantic AI is the strongest candidate**, and the "stay custom + targeted libraries" path is the viable alternative. Every other framework fails on at least one critical dimension — vendor lock-in (ADK, Semantic Kernel), runtime ownership conflicts (LangGraph, AutoGen), memory system mismatches (CrewAI), paradigm mismatch (DSPy, LlamaIndex), or insufficient value (Haystack).

The recommended approach is a **hybrid adoption strategy**: adopt FastA2A immediately (framework-agnostic, low risk), prototype one KAOS agent with Pydantic AI to validate integration, then migrate the agent loop incrementally if the prototype succeeds. KAOS should keep ownership of memory (Redis), observability (OTel), deployment (K8s operator), and MCP tools (FastMCP) regardless of framework choice. The framework should own only the agent execution loop and model interaction layer — anything more creates coupling that conflicts with KAOS's architecture.

The key risks are Pydantic AI's pre-1.0 API instability (mitigated by version pinning and interface wrapping) and the universal "vendor gravity" problem where frameworks push their commercial observability and cloud services. KAOS's existing custom code works well; the question is not "which framework must we adopt?" but "does any framework make KAOS meaningfully better?" Pydantic AI does — it reduces agent code complexity, adds type-safe structured outputs, improves MCP and A2A capabilities, and provides a cleaner developer experience for users building custom agents. But if the team's risk tolerance is low, staying custom and adopting only FastA2A is a defensible choice.

## Framework Rankings

| Rank | Framework | Fit Score | One-Line Justification |
|------|-----------|-----------|------------------------|
| 1 | **Pydantic AI** | **9/10** | Thin, type-safe, BYO-everything library with native A2A + MCP — architecturally aligned with KAOS |
| 2 | **Stay Custom + Libraries** | **8/10** | Current code works; adopt FastA2A + DSPy as targeted libraries without framework risk |
| 3 | **Google ADK** | **9/10 arch, REJECTED** | Best memory/A2A alignment but GCP lock-in is a non-starter (confirmed by team experience) |
| 4 | **LangChain/LangGraph** | **6/10** | Largest ecosystem but over-abstraction, LangSmith lock-in, runtime conflicts, dependency bloat |
| 5 | **Semantic Kernel** | **6/10** | Good OTel but C#-first, Python features "Experimental", Azure gravity |
| 6 | **LlamaIndex** | **6/10** | RAG-first framework doing agents — paradigm mismatch; useful inside agents, not as foundation |
| 7 | **CrewAI** | **5/10** | Impressive memory but hidden LLM costs, LanceDB not distributed, Enterprise gating, no MCP/A2A |
| 8 | **AutoGen** | **5/10** | gRPC runtime conflicts with HTTP-based KAOS, post-rewrite instability, Azure gravity |
| 9 | **DSPy** | **5/10 (7 as inner layer)** | Wrong tool for orchestration — excellent for prompt optimization as an optional inner library |
| 10 | **Haystack** | **4/10** | Well-engineered pipelines, but doesn't solve KAOS's actual problems |

## Key Findings

### From STACK.md — Technology Recommendations

Pydantic AI is the only framework whose design philosophy — thin layer, type-safe, bring-your-own-everything via dependency injection — aligns with KAOS's architecture. No framework is a drop-in replacement; every option requires KAOS to retain ownership of memory, observability, and deployment.

**Core technologies (recommended path):**
- **Pydantic AI** (pre-1.0, MIT): Agent execution loop + model interaction — replaces ~993-line client.py with cleaner, typed API
- **FastA2A** (Pydantic team, MIT): A2A protocol implementation — Starlette-based, framework-agnostic, enhances existing HTTP A2A
- **FastMCP** (unchanged): MCP tool integration — directly compatible with Pydantic AI
- **LiteLLM** (unchanged): Model routing — Pydantic AI supports it as a provider
- **Redis** (unchanged): Distributed memory — injected as Pydantic AI dependency
- **OpenTelemetry** (unchanged): Observability — Pydantic AI emits OTel-compatible spans

### From FEATURES.md — Feature Landscape

**Table stakes (KAOS already has):**
- Session-scoped memory, LLM provider agnosticism, tool/function calling, SSE streaming, MCP client, OTel tracing

**Table stakes (KAOS missing — prioritize):**
- Structured output validation — expected in 2026, Pydantic AI provides this natively
- Model fallback/failover — low complexity via LiteLLM, high production value

**Should-have (differentiators to add):**
- A2A protocol compliance — standardize existing A2A on the protocol spec (incremental)
- MCP server support — expose KAOS agents as MCP servers (enables IDE/tool discovery)
- Type-safe dependency injection — Pydantic AI's core differentiator

**Defer (v2+):**
- Semantic/long-term memory — valuable but high engineering cost; wait for demand
- Durable execution — adds complexity, not table stakes yet
- Bidi/audio/video streaming — niche (only Google ADK has this)
- No-code visual builder — massive effort, low alignment with developer-tool positioning
- Multi-language SDKs — Python-only; OpenAI-compatible API means any language can consume agents

**Anti-features (explicitly avoid):**
- Proprietary observability (LangSmith, Logfire as primary)
- Cloud-locked memory (Vertex AI, Azure)
- Graph-based state machines (LangGraph complexity)
- Role/persona agent definitions (CrewAI over-abstraction)

### From ARCHITECTURE.md — Integration Patterns

KAOS's container contract (env-var injection, health probes, port 8000, K8s operator lifecycle) is the immovable constraint. Any framework must work as a **library within KAOS's pod**, not as a platform that owns the runtime. Three integration patterns were identified:

**Recommended: Pattern C (Adapter layer)**
1. **kaos-pydanticai-adapter** — reads env vars, creates `pydantic_ai.Agent`, wraps with FastAPI, exposes required endpoints, bridges KAOS memory. Estimated: 1-2 weeks.
2. **kaos-adk-adapter** — rejected due to GCP lock-in despite high architectural alignment (9/10 fit score).
3. **kaos-langchain-adapter** — Tier 2, 3-4 weeks, only if ecosystem reach is needed.

**Key architectural insight:** A2A protocol support is the biggest framework differentiator. Only Pydantic AI (FastA2A) and Google ADK have native support. Since KAOS's core value is K8s-managed multi-agent orchestration, A2A support is a critical selection criterion.

**Infrastructure prerequisite:** Before any framework adapter, KAOS needs a formalized adapter contract (required endpoints, env var contract, memory interface, OTel interface) and a CRD `spec.framework` field.

### From PITFALLS.md — Critical Risks

**Top 5 pitfalls to avoid:**

1. **Memory system replacement trap** — Frameworks that insist on managing memory (CrewAI, LangChain) conflict with KAOS's working RedisMemory. **Rule:** Framework must have zero opinion on memory, or trivially support Redis without abstraction layers.

2. **Runtime ownership conflict** — Frameworks that assume they own the runtime (LangGraph durable execution, ADK Agent Engine, AutoGen gRPC runtime) conflict with K8s operator. **Rule:** Framework must work as a library within KAOS's pod.

3. **Vendor lock-in through observability** — LangSmith, Logfire, Azure Monitor create dependencies through the "easy path." **Rule:** KAOS uses OTel; framework must support it natively.

4. **Abstraction tax exceeding value** — LangChain-style over-abstraction where the framework makes simple operations harder. **Rule:** If framework makes operations harder to understand/debug, it's negative value.

5. **Community resource staleness** — AutoGen and LangChain have large communities but significant portions reference rewritten/deprecated APIs. **Rule:** Only trust current official docs.

**Cross-cutting detection pattern (from ADK failure):** When a framework is backed by a cloud vendor, verify that (1) pluggable interfaces are actually used with non-vendor backends, (2) documentation doesn't default to vendor services, and (3) the non-vendor path is well-tested, not just theoretically possible.

## Recommendation

**Primary: Adopt Pydantic AI via hybrid approach**

1. **Immediate** — Adopt FastA2A for A2A communication (framework-agnostic, zero risk)
2. **Phase 1** — Define adapter contract and CRD extension (`spec.framework` field)
3. **Phase 2** — Build Pydantic AI adapter, prototype with one real agent
4. **Phase 3** — If prototype succeeds, migrate agent loop incrementally
5. **Throughout** — Keep RedisMemory, OTel, K8s operator, FastMCP, LiteLLM unchanged

**If Pydantic AI is rejected after prototype:** Fall back to "Stay Custom + FastA2A + DSPy-as-library." This is the zero-risk path that still adds value.

**Do not adopt:** LangChain, CrewAI, AutoGen, Google ADK, Semantic Kernel, LlamaIndex, or Haystack as the framework foundation. DSPy and LlamaIndex may be offered as optional libraries within individual agents.

## Critical Tradeoffs

| Tradeoff | Pydantic AI Path | Stay Custom Path |
|----------|------------------|------------------|
| Agent code complexity | **Lower** — cleaner API, typed deps, structured outputs | Higher — current ~993-line client.py |
| API stability risk | **Pre-1.0 risk** — breaking changes possible | Full control |
| Developer experience | **Better** — declarative agent definition via DI | Current — users extend Python classes |
| A2A capabilities | **Enhanced** — FastA2A protocol compliance | Current — HTTP-based, works |
| MCP integration | **Enhanced** — native + FastMCP, can expose as MCP server | Current — FastMCP only, works |
| Maintenance burden | **Lower** — framework handles agent loop | Higher — maintain custom loop |
| Framework coupling | **New dependency** — manageable via adapter pattern | None |
| Upgrade risk | **Quarterly version management** needed | Only dependency upgrades |
| Time to adopt | **2-4 weeks** for core migration | Zero |
| Community support | Growing but small (15K stars) | Self-supported |

## Risk Assessment

| Risk | Severity | Probability | Mitigation |
|------|----------|-------------|------------|
| Pydantic AI pre-1.0 breaking changes | MEDIUM | HIGH | Pin versions, wrap behind KAOS interfaces (adapter pattern) |
| Framework coupling makes KAOS harder to maintain | MEDIUM | LOW | Thin adapter layer; framework only owns agent loop |
| Logfire commercial pressure increases | LOW | MEDIUM | Use OTel directly from day 1; never adopt Logfire |
| FastA2A development slows/stops | LOW | LOW | FastA2A is Starlette-based; KAOS can fork or replace with direct HTTP |
| Pydantic AI direction diverges from KAOS needs | MEDIUM | LOW | Interface wrapping provides escape hatch; "rip and replace" plan documented |
| Over-engineering the adapter layer | MEDIUM | MEDIUM | Anti-pattern #4: if adapter exceeds 30% of replaced code, simplify |
| Analysis paralysis delays framework decision | LOW | MEDIUM | Research is clear — prototype Pydantic AI, decide based on results |

## Next Steps

1. **Decision gate:** Team reviews this research and decides between "Adopt Pydantic AI (hybrid)" or "Stay Custom + FastA2A." Both are validated paths.

2. **If adopting Pydantic AI:**
   - Define the adapter contract (required endpoints, env var mapping, memory/OTel interfaces)
   - Extend CRD with `spec.framework` field
   - Build `kaos-adapter-pydanticai` package
   - Prototype with one production agent
   - Evaluate: is the adapter simpler than what it replaces?

3. **Regardless of framework decision:**
   - Adopt FastA2A for A2A protocol compliance (zero risk, high value)
   - Add model fallback/failover (surface LiteLLM's existing capability)
   - Add structured output validation (table stakes in 2026)
   - Consider MCP server support (expose agents as MCP servers)

4. **Feature priorities from research:**
   - P1: Model fallback/failover (low effort, high value)
   - P1: Structured output validation (table stakes)
   - P2: A2A protocol compliance via FastA2A
   - P2: MCP server support
   - P3: Semantic/long-term memory (defer, wait for demand)
   - P3: Durable execution (defer, high complexity)

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | All 9 frameworks evaluated against official documentation; Pydantic AI recommendation well-supported |
| Features | **MEDIUM-HIGH** | Feature matrices based on official docs; some confidence gaps on LangChain/AutoGen internals |
| Architecture | **MEDIUM-HIGH** | Pydantic AI, Google ADK, AutoGen: HIGH confidence; others: MEDIUM from docs + inference |
| Pitfalls | **HIGH** | ADK pitfalls confirmed from team experience; framework risks well-documented in ecosystem |

**Overall confidence:** HIGH — Research is comprehensive, sources are official documentation, and the recommendation is consistent across all four dimensions.

### Gaps to Address

- **Pydantic AI production scale validation:** No evidence of Pydantic AI at KAOS's scale (distributed K8s, many agent pods). Prototype must validate this.
- **FastA2A maturity:** FastA2A is young; assess whether it handles KAOS's A2A edge cases (discovery, error handling, timeouts).
- **Adapter complexity estimation:** 1-2 week estimate for Pydantic AI adapter is based on docs analysis, not implementation. Prototype will validate.
- **User impact of framework change:** How does Pydantic AI affect users building custom KAOS agent images? Needs UX evaluation during prototype.
- **Memory bridging complexity:** Converting KAOS MemoryEvents ↔ Pydantic AI message_history is "non-trivial" per architecture research. Needs spike.

## Implications for Roadmap

### Phase 1: Framework Infrastructure
**Rationale:** Before any framework integration, formalize the adapter contract and extend the CRD. This is foundational work that de-risks all subsequent phases.
**Delivers:** Adapter contract definition, CRD `spec.framework` field, container image strategy
**Addresses:** Architecture prerequisite from ARCHITECTURE.md
**Avoids:** Anti-pattern #4 (over-engineering) by defining clear boundaries first
**Research needed:** No — standard K8s CRD extension patterns

### Phase 2: Quick Wins (Framework-Independent)
**Rationale:** These features are valuable regardless of framework choice and have clear implementation paths.
**Delivers:** Model fallback/failover, structured output validation
**Addresses:** Table stakes gaps from FEATURES.md
**Avoids:** Analysis paralysis on framework decision
**Research needed:** No — LiteLLM fallback is documented; Pydantic validation is well-established

### Phase 3: Pydantic AI Adapter + FastA2A
**Rationale:** Prototype Pydantic AI integration and adopt FastA2A for A2A protocol compliance. This is the highest-value framework work.
**Delivers:** `kaos-adapter-pydanticai` package, A2A protocol compliance, MCP server support
**Addresses:** A2A protocol compliance, MCP server support from FEATURES.md
**Avoids:** Memory replacement trap (Redis stays); runtime ownership conflict (adapter pattern)
**Research needed:** YES — Pydantic AI adapter is novel integration; need `/gsd-research-phase` for memory bridging and endpoint mapping details

### Phase 4: Production Validation + Ecosystem
**Rationale:** If Phase 3 prototype succeeds, harden for production. If it fails, fall back to custom.
**Delivers:** Production-ready adapter, integration tests, user documentation, optional DSPy integration
**Addresses:** User extensibility from FEATURES.md, escape hatch planning from PITFALLS.md
**Avoids:** Demo-driven adoption (Anti-pattern #2) — production validation catches issues demos miss
**Research needed:** Partial — DSPy integration is well-scoped; production hardening follows standard patterns

### Phase Ordering Rationale

- **Infrastructure first** because adapter contract definition is prerequisite for all framework work and costs nothing if framework is rejected
- **Quick wins second** because they're framework-independent and immediately valuable — team isn't blocked on framework decision
- **Pydantic AI third** because it has the smallest integration surface (1-2 weeks) and highest architectural alignment (9/10) — prototype validates the recommendation
- **Production last** because it depends on prototype success — this is the "go/no-go" gate

### Research Flags

**Needs deeper research during planning:**
- **Phase 3 (Pydantic AI Adapter):** Memory bridging (MemoryEvents ↔ message_history), A2A endpoint alignment (`/.well-known/agent.json` vs `/.well-known/agent`), FastA2A edge cases
- **Phase 4 (User Impact):** How custom agent image workflows change with Pydantic AI; user migration guide needs investigation

**Standard patterns (skip research):**
- **Phase 1 (CRD Extension):** Well-documented K8s CRD patterns
- **Phase 2 (Quick Wins):** LiteLLM fallback and Pydantic validation are established

## Sources

### Primary (HIGH confidence)
- Pydantic AI official docs (ai.pydantic.dev) — agent model, MCP, A2A/FastA2A, Logfire/OTel, models
- Google ADK official docs (google.github.io/adk-docs) — memory, A2A, MCP, deployment
- CrewAI official docs (docs.crewai.com) — memory deep-dive, agent model
- KAOS source code — server.py, client.py, memory.py, telemetry/manager.py, agent_controller.go
- KAOS team ADK rejection experience — direct validation of GCP lock-in

### Secondary (MEDIUM-HIGH confidence)
- AutoGen stable docs (microsoft.github.io/autogen) — post-rewrite architecture
- Semantic Kernel docs (learn.microsoft.com) — observability, agent framework, experimental flags
- LangChain/LangGraph docs — architecture overview, memory, orchestration
- Haystack docs (docs.haystack.deepset.ai) — pipeline model, agent component
- DSPy docs (dspy.ai) — signatures, modules, optimizers, MCP

### Tertiary (MEDIUM confidence)
- GitHub star counts for all frameworks — point-in-time indicators, not definitive quality measures
- Framework architecture internals — inferred from docs + training data where deep-dive wasn't possible
- Community sentiment (LangChain fatigue, AutoGen rewrite confusion) — anecdotal but consistent

---
*Research completed: 2026-02-20*
*Ready for roadmap: yes*
