# Domain Pitfalls: Agentic AI Framework Adoption for KAOS

**Domain:** Kubernetes-native agent orchestration platform — Python data-plane framework evaluation
**Researched:** 2026-02-20

---

## Lessons from the ADK Failure

Before evaluating each framework, KAOS's experience rejecting Google ADK provides a concrete pattern of what goes wrong:

| What was promised | What actually happened |
|---|---|
| "Model-agnostic" | Optimized for Gemini; other providers were second-class |
| Distributed memory | Only `InMemoryMemoryService` (ephemeral) and `VertexAiMemoryBankService` (GCP-locked) |
| A2A communication | Over-abstracted protocol implementation that was inflexible in practice |
| Easy deployment | Deployment docs focused on Agent Engine, Cloud Run, GKE — all GCP services |

**Root cause:** ADK is a distribution channel for Google Cloud, not a neutral framework. The "open source" surface conceals deep GCP assumptions.

**Detection pattern to apply to all frameworks:** When a framework is backed by a cloud vendor, check:
1. Are the "pluggable" interfaces actually used with non-vendor backends?
2. Does the documentation default to vendor services?
3. Is the non-vendor path well-tested, or just theoretically possible?

---

## Critical Pitfalls (Framework-Specific)

### 1. Pydantic AI — Young Framework Risk

**Stars:** ~15K | **Maturity:** Young (launched late 2024)
**Overall Risk Level:** MEDIUM

**What goes wrong:** Adopting a young framework means APIs will change, edge cases aren't covered, and the community is small for troubleshooting.

| Risk | Severity | Details |
|---|---|---|
| API instability | MEDIUM | Pre-1.0 framework; expect breaking changes as it matures |
| Small ecosystem | MEDIUM | 15K stars — smallest of evaluated frameworks; fewer community solutions |
| Logfire push | LOW | Observability defaults to Pydantic Logfire; OTel supported but Logfire is the "easy path" |
| No built-in memory | LOW for KAOS | No distributed memory — you bring your own. Actually a feature for KAOS (keep Redis) |
| Limited agent patterns | MEDIUM | Simple agent loop; complex multi-agent orchestration patterns not yet proven at scale |

**Why it happens:** Pydantic AI is built by the Pydantic team, who have excellent track record (Pydantic, FastAPI ecosystem) but the agentic AI space moves fast and the framework is still finding its shape.

**Prevention for KAOS:**
- Pin versions strictly; wrap framework APIs behind KAOS interfaces
- The dependency injection system is well-designed — use it for KAOS's memory/telemetry integration
- FastA2A is Starlette-based and framework-agnostic — good escape hatch
- No memory lock-in (bring your own Redis) is actually ideal for KAOS

**Detection:** Watch GitHub release cadence. If breaking changes are frequent in patch/minor versions, that's a red flag.

---

### 2. LangChain/LangGraph — Abstraction Tax

**Stars:** ~127K / ~25K | **Maturity:** Established (2022+)
**Overall Risk Level:** HIGH

**What goes wrong:** LangChain's notorious over-abstraction creates a "framework within a framework" problem. You spend more time fighting LangChain than building your product.

| Risk | Severity | Details |
|---|---|---|
| Over-abstraction | HIGH | Multiple abstraction layers for simple operations; simple LLM calls become complex chains |
| Breaking changes history | HIGH | Major API churn from chains → LCEL → LangGraph; community burned repeatedly |
| LangSmith lock-in | MEDIUM | Observability pushes LangSmith hard; OTel possible but not the default path |
| Massive dependency tree | HIGH | Pulls in hundreds of transitive dependencies; bloats container images |
| Two-framework confusion | MEDIUM | LangChain vs LangGraph vs LangChain Core — which one to use? Moving target |
| Performance overhead | MEDIUM | Abstraction layers add latency to every LLM call and tool invocation |
| Debugging difficulty | HIGH | Stack traces through multiple abstraction layers are painful to diagnose |

**Why it happens:** LangChain was built as a general-purpose LLM abstraction when the space was new. It tried to abstract everything, resulting in leaky abstractions that are worse than the underlying APIs.

**Consequences for KAOS:**
- LangGraph's durable execution model assumes LangGraph manages the runtime — conflicts with K8s operator model
- Memory implementations exist but are LangChain-ecosystem-specific; Redis is supported but through LangChain's abstractions
- Container image size will increase significantly (dependency bloat)
- Users building custom agents would need to learn LangChain's abstractions on top of KAOS's concepts

**Prevention:**
- If using LangGraph, use it for orchestration only — avoid LangChain abstractions for LLM calls
- Keep LiteLLM for model routing; don't adopt LangChain's model abstraction
- Budget significant time for version upgrades and breaking changes

**Detection:** If your wrapper code around LangChain is approaching the complexity of what LangChain replaces, you've hit the abstraction tax.

---

### 3. CrewAI — Hidden Complexity in Memory

**Stars:** ~44K | **Maturity:** Established (2023+)
**Overall Risk Level:** MEDIUM-HIGH

**What goes wrong:** CrewAI's memory system looks impressive (hierarchical scopes, composite scoring, LLM-powered analysis) but introduces hidden LLM calls and vendor-specific defaults.

| Risk | Severity | Details |
|---|---|---|
| Memory LLM calls | HIGH | Memory save/recall triggers additional LLM calls for analysis — hidden cost and latency |
| LanceDB default storage | MEDIUM | Default memory storage is local LanceDB — not distributed-ready out of the box |
| Enterprise tier gating | MEDIUM | Key deployment/scaling features behind commercial "Enterprise" tier |
| Opinionated agent model | MEDIUM | Role/Goal/Backstory pattern is rigid; doesn't map to all agent architectures |
| Embedding provider coupling | MEDIUM | Memory system requires embedder configuration; defaults may not match KAOS needs |
| Black-box orchestration | MEDIUM | "Crew" orchestration decisions are opaque; hard to debug why agents interact certain ways |

**Why it happens:** CrewAI optimizes for the "team of agents" demo use case. The memory system is sophisticated but assumes you want LLM-powered memory management, which adds cost and unpredictability.

**Consequences for KAOS:**
- Replacing KAOS's simple RedisMemory with CrewAI's memory system would add latency (LLM calls) and cost
- The LanceDB default doesn't work for distributed K8s pods — would need to swap to a distributed store
- Enterprise features behind a paywall conflict with KAOS being open-source
- The Role/Goal/Backstory pattern is more restrictive than KAOS's current flexible agent model

**Prevention:**
- If adopting, disable LLM-powered memory features and implement simple session memory
- Plan to replace LanceDB storage backend with Redis
- Avoid features that are Enterprise-only

**Detection:** Monitor LLM API costs — if memory operations are consuming significant tokens, the hidden LLM calls are the cause.

---

### 4. Google ADK — Confirmed GCP Lock-In

**Stars:** ~18K | **Maturity:** Young (2025)
**Overall Risk Level:** CRITICAL (for KAOS)

**What goes wrong:** Already experienced by KAOS. Memory is GCP-locked, deployment assumes GCP services, "model-agnostic" claims don't hold up.

| Risk | Severity | Details |
|---|---|---|
| Memory GCP lock-in | CRITICAL | Only InMemoryMemoryService (no persistence) and VertexAiMemoryBankService (GCP) |
| Deployment GCP assumption | HIGH | Docs focus on Agent Engine, Cloud Run, GKE |
| A2A over-abstraction | HIGH | Protocol implementation is inflexible, adds unnecessary abstraction |
| Gemini optimization | MEDIUM | Claims model-agnostic but optimized for Gemini |
| Young framework | MEDIUM | Launched 2025; rapid changes expected |

**Why it happens:** ADK is Google's developer funnel into GCP services. Open-sourcing the framework creates adoption that flows into paid services.

**Consequences for KAOS:** Already known — this was rejected. Documented here for completeness and as a reference pattern.

**Prevention:** Don't adopt. If forced to revisit, wait for community-contributed memory backends and non-GCP deployment patterns. Verify claims don't believe marketing.

---

### 5. AutoGen — Rewrite Instability

**Stars:** ~55K | **Maturity:** Established but recently rewritten
**Overall Risk Level:** MEDIUM-HIGH

**What goes wrong:** AutoGen underwent a major rewrite from 0.2 to the current version. The new architecture (AgentChat, Core, Extensions, Studio) is complex and the migration path from 0.2 was not smooth. Many community resources and tutorials reference the old API.

| Risk | Severity | Details |
|---|---|---|
| Post-rewrite instability | HIGH | Major architecture rewrite; new APIs may still be settling |
| Multi-package complexity | MEDIUM | AgentChat + Core + Extensions + Studio — which to use and how they interact is confusing |
| Stale community resources | HIGH | Most tutorials/StackOverflow answers reference 0.2 API; current docs are authoritative but community knowledge lags |
| Microsoft ecosystem pull | MEDIUM | Azure integration is well-supported; other clouds are afterthought |
| Distributed runtime complexity | MEDIUM | GrpcWorkerAgentRuntime for distributed agents adds gRPC dependency and complexity |
| Studio dependency | LOW | Studio (no-code UI) is separate concern but creates expectation mismatch |

**Why it happens:** Microsoft rebuilt AutoGen from scratch to address fundamental architecture issues. The rewrite was necessary but creates an ecosystem in transition.

**Consequences for KAOS:**
- GrpcWorkerAgentRuntime conflicts with KAOS's HTTP-based agent communication model
- Multi-package architecture means more dependency surface to manage
- Azure-optimized paths may subtly bias provider choices
- Community help will be unreliable (old vs new API confusion)

**Prevention:**
- Only use current (post-rewrite) APIs; ignore 0.2 documentation entirely
- Use Core package for event-driven architecture; skip AgentChat if it's too opinionated
- Verify all AutoGen code against current official documentation, not community posts
- Plan for another round of breaking changes as the rewrite matures

**Detection:** If StackOverflow answers don't match official docs, you're looking at 0.2 advice.

---

### 6. Semantic Kernel — C# First, Python Second

**Stars:** ~27K | **Maturity:** Established
**Overall Risk Level:** MEDIUM

**What goes wrong:** Semantic Kernel is Microsoft's enterprise AI middleware. The C# implementation is the primary citizen; Python support lags behind with many features marked "Experimental."

| Risk | Severity | Details |
|---|---|---|
| Python as second-class | HIGH | C# gets features first; Python implementation lags; many Python features are "Experimental" |
| Experimental API churn | HIGH | Features marked "Experimental" can change or be removed without notice |
| Azure ecosystem gravity | MEDIUM | Azure OpenAI and Azure AI services are the default/best-documented paths |
| Enterprise complexity | MEDIUM | Designed for enterprise patterns that may be overkill for KAOS's agent model |
| Plugin system overhead | LOW | OpenAPI-based plugin system adds indirection for simple tool calls |
| Limited agent orchestration | MEDIUM | Not primarily an agent orchestration framework; agent patterns are bolted on |

**Why it happens:** Semantic Kernel started as a C# SDK for Azure OpenAI. Python and Java ports followed but are maintained by a smaller team with lower priority.

**Consequences for KAOS:**
- Building on "Experimental" Python APIs means KAOS would inherit instability
- Azure-first documentation means constant translation to provider-agnostic patterns
- Plugin system (OpenAPI-based) is different from MCP — would need to maintain both or choose one
- Not designed for the K8s-native distributed agent model KAOS uses

**Prevention:**
- Only adopt features that are GA (not Experimental) in Python
- Verify every Azure example works with non-Azure providers before committing
- Use as lightweight middleware only, not as the orchestration layer

**Detection:** Check Python SDK release notes for "Experimental" warnings. If core features you need are Experimental, wait.

---

### 7. LlamaIndex — RAG Framework Doing Agents

**Stars:** ~47K | **Maturity:** Established (for RAG)
**Overall Risk Level:** MEDIUM

**What goes wrong:** LlamaIndex is excellent at RAG but agent orchestration is a newer, secondary capability. Adopting it for agents means using a RAG framework's worldview for an orchestration problem.

| Risk | Severity | Details |
|---|---|---|
| RAG-centric worldview | HIGH | Everything is viewed through the lens of "index, retrieve, synthesize" — agent patterns are adapted to fit this |
| LlamaCloud push | MEDIUM | Commercial LlamaCloud is the "easy" path; self-hosted requires more effort |
| Surface area bloat | MEDIUM | Massive package with RAG, agents, workflows, evaluation, etc. — most not needed for KAOS |
| Agent maturity | MEDIUM | LlamaAgents/Workflows are newer than core RAG capabilities; less battle-tested |
| Dependency weight | MEDIUM | Large dependency tree from RAG infrastructure even if only using agent features |
| Rapid iteration | LOW | Frequent releases; API surface changes as agent capabilities evolve |

**Why it happens:** LlamaIndex built a dominant RAG framework and is expanding into agents/orchestration. The agent capabilities are real but secondary to the RAG mission.

**Consequences for KAOS:**
- Pulling in LlamaIndex for agent orchestration brings unnecessary RAG infrastructure
- Workflow patterns may not map well to KAOS's K8s-native pod-per-agent model
- LlamaCloud integration pressure similar to LangSmith/Logfire push from other frameworks
- Community expertise is RAG-focused; agent orchestration help will be limited

**Prevention:**
- If adopting, use only `llama-index-core` agent/workflow modules; avoid RAG infrastructure
- Don't let LlamaIndex's RAG patterns influence KAOS's agent architecture
- Keep memory and retrieval as KAOS-managed concerns, not LlamaIndex-managed

**Detection:** If you find yourself building RAG pipelines when you just needed agent orchestration, you've been captured by the framework's worldview.

---

### 8. Haystack — Niche Community

**Stars:** ~24K | **Maturity:** Established (post v2 rewrite)
**Overall Risk Level:** LOW-MEDIUM

**What goes wrong:** Haystack is well-engineered (low issue count, clean v2 rewrite) but has a smaller community and enterprise-backed (deepset) direction that may not align with KAOS.

| Risk | Severity | Details |
|---|---|---|
| Smaller community | MEDIUM | 24K stars; less community content, fewer third-party integrations |
| Pipeline-centric model | MEDIUM | Pipeline-based architecture may conflict with KAOS's agent loop model |
| deepset enterprise direction | LOW | Enterprise offering exists but open-source core is well-maintained |
| Post-rewrite ecosystem | MEDIUM | v2 was a major rewrite from v1; some ecosystem components may still lag |
| Agent capabilities | MEDIUM | Primarily a pipeline framework; agent patterns are a subset of capabilities |
| Limited agent orchestration | MEDIUM | Not designed for multi-agent orchestration at KAOS's level of complexity |

**Why it happens:** Haystack focuses on building reliable NLP/AI pipelines. Agent orchestration is supported but not the primary mission.

**Consequences for KAOS:**
- Pipeline model would need adaptation for KAOS's agentic loop pattern
- Smaller community means less help with edge cases
- Clean engineering is a plus, but limited agent-specific features mean more custom code anyway

**Prevention:**
- Evaluate whether Haystack's pipeline model genuinely simplifies KAOS's agent runtime
- If the pipeline model requires significant adaptation, the framework isn't adding value

**Detection:** If you're writing as much custom agent code with Haystack as without it, the framework isn't helping.

---

### 9. DSPy — Paradigm Mismatch

**Stars:** ~32K | **Maturity:** Research-grade becoming production
**Overall Risk Level:** MEDIUM-HIGH (for KAOS specifically)

**What goes wrong:** DSPy is a fundamentally different paradigm — "programming, not prompting." It focuses on optimizing prompts/weights programmatically using signatures, modules, and optimizers. This is powerful but solves a different problem than what KAOS needs.

| Risk | Severity | Details |
|---|---|---|
| Paradigm mismatch | HIGH | DSPy optimizes prompt engineering; KAOS needs agent orchestration infrastructure |
| Academic origins | MEDIUM | Stanford NLP research project; production patterns may not be well-established |
| Learning curve | HIGH | Signatures, modules, optimizers, assertions — new mental model that team must learn |
| LiteLLM dependency | LOW for KAOS | Uses LiteLLM internally — aligns with KAOS but means shared dependency management |
| Limited orchestration | HIGH | Not designed for multi-agent distributed orchestration |
| Deployment model gap | HIGH | No built-in concepts for K8s-native, distributed, pod-per-agent deployment |

**Why it happens:** DSPy solves prompt optimization and LLM program composition. It's excellent at what it does, but "agent orchestration platform" is not what it does.

**Consequences for KAOS:**
- Adopting DSPy would require building all orchestration infrastructure anyway
- The paradigm shift (signatures/modules/optimizers) adds learning burden without addressing KAOS's core needs
- DSPy could be used *within* KAOS agents for prompt optimization, but not *as* the framework

**Prevention:**
- Consider DSPy as an optional tool available to KAOS agent developers, not as the framework foundation
- Don't confuse "better prompts" with "better agent orchestration"

**Detection:** If the team is spending time learning DSPy optimizers instead of building distributed agent features, priorities have drifted.

---

## Risk Comparison Matrix

| Framework | Provider Lock-in | Memory Compatibility | API Stability | K8s Fit | OTel Support | A2A Support | MCP Support | Community Size | Overall Risk |
|---|---|---|---|---|---|---|---|---|---|
| **Pydantic AI** | LOW (no vendor) | ✅ BYO (ideal) | MEDIUM (young) | GOOD | ✅ (+ Logfire) | ✅ FastA2A | ✅ Native | Small (15K) | **MEDIUM** |
| **LangChain/LangGraph** | MEDIUM (LangSmith) | ⚠️ Abstracted | LOW (churn history) | POOR (owns runtime) | ⚠️ LangSmith push | ⚠️ Limited | ✅ Yes | Huge (127K) | **HIGH** |
| **CrewAI** | MEDIUM (Enterprise) | ⚠️ LanceDB default, LLM calls | MEDIUM | MEDIUM | ⚠️ Limited | ⚠️ Limited | ⚠️ Limited | Large (44K) | **MEDIUM-HIGH** |
| **Google ADK** | CRITICAL (GCP) | ❌ GCP-locked | LOW (young) | POOR (GCP deploy) | ⚠️ GCP-native | ⚠️ Over-abstracted | ✅ Yes | Medium (18K) | **CRITICAL** |
| **AutoGen** | MEDIUM (Azure) | ⚠️ Complex | LOW (rewrite) | MEDIUM (gRPC) | ⚠️ Limited | ⚠️ gRPC-based | ✅ McpWorkbench | Large (55K) | **MEDIUM-HIGH** |
| **Semantic Kernel** | MEDIUM (Azure) | ⚠️ Experimental | LOW (Experimental) | MEDIUM | ⚠️ Azure-native | ❌ Limited | ⚠️ Plugin model | Medium (27K) | **MEDIUM** |
| **LlamaIndex** | MEDIUM (LlamaCloud) | ⚠️ RAG-centric | MEDIUM | MEDIUM | ⚠️ Limited | ⚠️ Limited | ✅ Yes | Large (47K) | **MEDIUM** |
| **Haystack** | LOW (deepset) | ⚠️ Pipeline-based | MEDIUM (post v2) | MEDIUM | ⚠️ Limited | ❌ Limited | ⚠️ Limited | Small (24K) | **LOW-MEDIUM** |
| **DSPy** | LOW (academic) | ❌ Not applicable | MEDIUM | POOR (no deployment model) | ❌ None | ❌ None | ✅ Yes | Medium (32K) | **MEDIUM-HIGH** |

### Legend
- ✅ = Good fit / well-supported
- ⚠️ = Partial / requires work
- ❌ = Poor fit / not supported

---

## Cross-Cutting Pitfalls

### Pitfall A: "Provider Agnostic" Claims

**What goes wrong:** Every framework claims provider agnosticism. In practice, the framework creator's preferred provider (or paying cloud partner) gets 90% of testing, documentation, and optimization.

**Pattern:**
| Framework | Claims | Reality |
|---|---|---|
| Google ADK | Model-agnostic | Gemini-optimized, GCP-locked memory |
| LangChain | All providers | LangSmith observability push |
| Semantic Kernel | Multi-provider | Azure OpenAI is the default path |
| AutoGen | Provider-flexible | Azure examples dominate docs |
| CrewAI | Provider-agnostic | Enterprise features gated |
| Pydantic AI | Model-agnostic | Logfire push (mild) |

**Prevention:** Keep LiteLLM as KAOS's model routing layer regardless of framework choice. Don't let any framework own the LLM provider abstraction.

---

### Pitfall B: Memory Vendor Lock-In

**What goes wrong:** Frameworks that provide "batteries-included" memory almost always default to a storage backend that doesn't match your production needs.

**Pattern by framework:**
- **ADK:** Vertex AI only (for persistence)
- **CrewAI:** LanceDB (local, not distributed)
- **LangChain:** Many backends but through LangChain's abstraction layer
- **Pydantic AI:** No built-in (BYO — best for KAOS)
- **AutoGen/SK/LlamaIndex/Haystack/DSPy:** Limited or no distributed memory

**Prevention:** KAOS's RedisMemory works. Any framework adopted must either:
1. Have no opinion on memory (let KAOS manage it), OR
2. Support Redis as a first-class, well-tested backend

Option 1 is strongly preferred.

---

### Pitfall C: A2A Protocol Maturity

**What goes wrong:** The A2A protocol is still young. Framework implementations vary in completeness and flexibility. Over-abstracted implementations (like ADK's) make it harder, not easier.

**Current state:**
- **Pydantic AI:** FastA2A — Starlette-based, framework-agnostic, most pragmatic implementation
- **Google ADK:** Over-abstracted, inflexible (KAOS rejected this)
- **Others:** Limited or no A2A-specific support

**Prevention:** A2A communication in KAOS is currently HTTP-based (`/v1/chat/completions`). This works and is simple. Any framework's A2A implementation should be evaluated against "is this simpler than what we have?" not "does it implement the A2A spec?"

---

### Pitfall D: MCP Tool Integration Conflicts

**What goes wrong:** KAOS currently uses FastMCP for tool integration. Some frameworks have their own MCP implementations that may conflict or add unnecessary abstraction.

**Pattern:**
- **Pydantic AI:** Multiple MCP methods including FastMCP client — compatible
- **LangChain:** Own tool abstraction; MCP is adapted to fit
- **AutoGen:** McpWorkbench extension — separate layer
- **DSPy:** MCP support exists
- **Others:** Varying levels of support

**Prevention:** Keep FastMCP as the tool integration layer. Don't let a framework replace it with its own abstraction unless that abstraction is strictly better.

---

### Pitfall E: Framework Coupling — The Escape Problem

**What goes wrong:** You adopt a framework for one feature (e.g., agent loop) and find it wants to own everything (memory, observability, tool calling, deployment). Leaving becomes expensive.

**Severity by framework:**
| Framework | Coupling Level | Escape Difficulty |
|---|---|---|
| Pydantic AI | LOW | Easy — thin layer, well-defined interfaces |
| LangChain/LangGraph | HIGH | Hard — deep abstraction, many touchpoints |
| CrewAI | MEDIUM-HIGH | Medium — memory system is deeply integrated |
| Google ADK | HIGH | Hard — GCP assumptions throughout |
| AutoGen | MEDIUM | Medium — multi-package but modular |
| Semantic Kernel | LOW-MEDIUM | Easy-Medium — middleware approach |
| LlamaIndex | MEDIUM | Medium — RAG infrastructure pulls you in |
| Haystack | LOW-MEDIUM | Easy-Medium — pipeline components are modular |
| DSPy | LOW | Easy — different paradigm, thin integration surface |

**Prevention:** Define KAOS's interfaces (memory, tools, telemetry, A2A) clearly. The framework plugs into KAOS's interfaces, not the reverse. If a framework requires KAOS to adapt to its interfaces, that's a red flag.

---

### Pitfall F: Upgrade Path Uncertainty

**What goes wrong:** Agentic AI frameworks are evolving rapidly. Major version changes can break entire integration layers.

**Recent breaking changes:**
- **LangChain:** Chains → LCEL → LangGraph (two paradigm shifts in 2 years)
- **AutoGen:** Complete rewrite from 0.2 to current version
- **Haystack:** v1 to v2 was a full rewrite
- **Semantic Kernel:** Frequent "Experimental" → "Deprecated" cycles in Python

**Prevention:**
- Wrap framework APIs behind KAOS-owned interfaces (adapter pattern)
- Limit framework surface area to the minimum needed
- Budget upgrade time quarterly
- Have a "rip and replace" plan — if a framework becomes unmaintainable, how long to replace it?

---

## Adoption Anti-Patterns

### Anti-Pattern 1: Adopting for One Feature, Getting Stuck on Ten

**Description:** You adopt CrewAI for its memory system, then discover it also wants to own agent orchestration, tool calling, and deployment. You end up fighting the framework on 9 things to use the 1 thing you wanted.

**Detection:** Count how many KAOS systems the framework wants to replace vs. how many you actually want replaced.

**Prevention:** List exactly which KAOS components the framework replaces. If it's more than 2-3, the coupling is too high.

---

### Anti-Pattern 2: Demo-Driven Adoption

**Description:** The framework's demo looks amazing — 5 lines to create a multi-agent system! In production, those 5 lines become 500 lines of configuration, error handling, and workarounds.

**Detection:** If your evaluation is based on "getting started" tutorials, you haven't evaluated the framework. Evaluate against KAOS's actual requirements: distributed memory, K8s deployment, OTel traces, MCP tools, A2A communication.

**Prevention:** Build a proof-of-concept that tests the hardest integration point (usually distributed memory + K8s deployment), not the easiest (basic agent loop).

---

### Anti-Pattern 3: Deployment Model Assumptions

**Description:** The framework assumes it controls the deployment model (LangGraph's durable execution, ADK's Agent Engine, CrewAI's Enterprise platform). KAOS already has a deployment model: K8s operator managing agent pods.

**Detection:** Does the framework's documentation describe how to deploy agents independently? Or does it assume a framework-managed runtime?

**Prevention:** Any framework adopted must work as a library within KAOS's existing pod-per-agent deployment model. If the framework assumes it IS the runtime, it's incompatible.

---

### Anti-Pattern 4: Over-Engineering the Integration

**Description:** You build an elaborate adapter layer between KAOS and the framework, handling every edge case. The adapter layer becomes as complex as the custom code it replaced.

**Detection:** If the adapter/integration code exceeds 30% of the code it replaces, you're over-engineering.

**Prevention:** Start with the thinnest possible integration. If the framework can't be used simply, it's the wrong framework.

---

### Anti-Pattern 5: Ignoring the "Stay Custom" Option

**Description:** Assuming a framework must be adopted because "everyone uses frameworks." KAOS's custom code works. The question isn't "which framework?" but "does any framework make KAOS better?"

**Detection:** If after evaluating all frameworks, the best integration requires significant adaptation, the answer might be "stay custom."

**Prevention:** Evaluate "stay custom + targeted library adoption" as a first-class option alongside full framework adoption.

---

## Top 5 Pitfalls to Avoid for KAOS

### 1. Memory System Replacement Trap
**Risk:** Adopting a framework that insists on managing memory (CrewAI, LangChain) when KAOS's RedisMemory works.
**Rule:** The framework must have NO OPINION on memory, or it must trivially support Redis without abstraction layers.

### 2. Runtime Ownership Conflict
**Risk:** Frameworks that assume they own the runtime (LangGraph's durable execution, ADK's Agent Engine) conflict with KAOS's K8s operator model.
**Rule:** The framework must work as a library within KAOS's pod, not as a runtime that manages KAOS.

### 3. Vendor Lock-In Through Observability
**Risk:** Frameworks push their commercial observability (LangSmith, Logfire, Azure Monitor). Adopting the "easy path" creates dependency.
**Rule:** KAOS uses OpenTelemetry. The framework must support OTel natively, not through a vendor-specific adapter.

### 4. Abstraction Tax Exceeding Value
**Risk:** LangChain-style over-abstraction where the framework's abstractions are more complex than the underlying operations.
**Rule:** If the framework makes simple operations harder to understand, debug, or modify, it's adding negative value.

### 5. Community Resource Staleness
**Risk:** AutoGen and LangChain have large communities but significant portions of community knowledge reference old/rewritten APIs.
**Rule:** Only trust official current documentation. Community posts must be verified against current API.

---

## Framework-Agnostic Recommendations

### 1. Interface-First Integration

Define KAOS's interfaces before choosing a framework:
```python
# KAOS owns these interfaces — framework must adapt to them
class MemoryProvider(Protocol):  # KAOS controls memory
class ToolProvider(Protocol):    # KAOS controls tools (FastMCP)
class TelemetryProvider(Protocol): # KAOS controls telemetry (OTel)
class AgentCommunication(Protocol): # KAOS controls A2A
```
The framework only owns the agent execution loop. Everything else stays KAOS-managed.

### 2. Thin Integration Layer

Maximum integration surface: agent loop + model calling. Everything else (memory, tools, telemetry, A2A, deployment) stays under KAOS's control.

### 3. Escape Hatch Planning

Before adopting any framework, document:
- Exactly which KAOS files/modules change
- How long to rip out the framework and return to custom code
- What the upgrade path looks like for the next major version

### 4. Proof-of-Concept Requirements

Any framework PoC must demonstrate:
1. ✅ Agent running in a K8s pod managed by the operator
2. ✅ RedisMemory working (not the framework's memory)
3. ✅ OTel traces exported (not the framework's observability)
4. ✅ MCP tools working via FastMCP (not the framework's tool system)
5. ✅ A2A communication between agent pods (not the framework's A2A)
6. ✅ Custom agent image built by a user (not locked to framework's packaging)

If any of these fail, the framework is not compatible with KAOS.

### 5. The "Library Not Framework" Principle

Prefer using framework components as libraries rather than adopting the full framework:
- Use Pydantic AI's agent loop without its server
- Use DSPy's optimizers without its agent model
- Use LangGraph's state machines without LangChain's abstractions

This gives KAOS the benefits without the coupling.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| Framework selection | Analysis paralysis — too many options | Use risk matrix above; eliminate HIGH/CRITICAL risk frameworks first |
| Proof of concept | Demo-driven evaluation | Test hardest integration (Redis memory + K8s deployment), not easiest (hello world) |
| Memory integration | Framework wants to own memory | Define memory interface; framework must adapt to KAOS's interface |
| Observability integration | Framework pushes vendor observability | Require OTel support from day 1; reject vendor-specific observability |
| A2A integration | Over-abstracted protocol | Keep HTTP-based A2A unless framework's approach is strictly simpler |
| Production deployment | Framework assumes it owns runtime | Framework must work as library within KAOS's existing K8s pod model |
| User extensibility | Framework's packaging conflicts with custom images | Verify users can build custom agents without framework-specific tooling |
| Upgrade planning | Major version breaks integration | Adapter pattern; limit framework surface area; quarterly upgrade budget |

---

## Sources

- Google ADK Memory documentation — confirmed only InMemoryMemoryService and VertexAiMemoryBankService (GCP)
- Pydantic AI documentation — A2A (FastA2A), MCP support, agent model, dependency injection
- LangChain/LangGraph documentation — architecture, memory, orchestration patterns
- CrewAI documentation — memory system (hierarchical scopes, LLM-powered analysis, LanceDB default)
- AutoGen documentation — post-rewrite architecture (AgentChat, Core, Extensions, Studio)
- Semantic Kernel documentation — AI services, plugin system, experimental feature warnings
- LlamaIndex documentation — agents, workflows, LlamaCloud integration
- Haystack documentation — pipeline architecture, v2 component model
- DSPy documentation — signatures, modules, optimizers paradigm
- GitHub statistics (stars, issues) for all frameworks — collected 2026-02-20
- KAOS project context — PROJECT.md, ARCHITECTURE.md, CONCERNS.md, STACK.md

**Confidence levels:**
- Framework capabilities and architecture: HIGH (verified from official docs)
- Risk assessments: MEDIUM-HIGH (based on documentation analysis + community patterns)
- ADK lock-in assessment: HIGH (confirmed from docs + KAOS team's direct experience)
- Community health indicators: MEDIUM (GitHub stars are imperfect proxy; issue counts vary)
