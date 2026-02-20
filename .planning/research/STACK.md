# Technology Stack: Agentic AI Framework Evaluation for KAOS

**Project:** KAOS — Kubernetes-Native Agent Orchestration Platform (Python Data-Plane)
**Researched:** 2026-02-20
**Overall confidence:** HIGH (all 9 frameworks evaluated against official documentation)

---

## Executive Summary

KAOS is a Kubernetes-native agent orchestration platform with a Go operator (control plane) and a Python agent runtime (data plane). The Python data-plane currently uses custom code for its agentic loop, distributed memory (Redis), MCP tool integration (FastMCP), OpenTelemetry observability, and agent-to-agent communication via HTTP. The team previously rejected Google ADK due to GCP/Vertex AI lock-in in memory and A2A implementations. This evaluation assesses whether any of 9 leading agentic AI frameworks should replace the custom code.

**Bottom line: Pydantic AI is the strongest candidate**, but the "stay custom + adopt targeted libraries" option remains viable. Pydantic AI's design philosophy — thin, type-safe, bring-your-own-everything via dependency injection — aligns with KAOS's requirements better than any other framework. It avoids the vendor lock-in traps (ADK, LangChain, Semantic Kernel), the over-abstraction tax (LangChain, CrewAI), and the paradigm mismatch (DSPy, LlamaIndex). Its first-class MCP support and pragmatic A2A implementation (FastA2A) are unique strengths.

No framework is a drop-in replacement. Every option requires KAOS to retain ownership of memory (Redis), observability (OTel), and deployment (K8s operator). The framework should only own the agent execution loop and model interaction layer. Anything more creates coupling that conflicts with KAOS's architecture.

---

## Framework Profiles

---

### 1. Pydantic AI

| Attribute | Details |
|-----------|---------|
| **Version** | Pre-1.0 (active development, launched late 2024) |
| **License** | MIT |
| **GitHub Stars** | ~15K |
| **Maintainer** | Pydantic team (Samuel Colvin et al.) |

#### Design Philosophy

Pydantic AI applies the Pydantic philosophy — type safety, validation, developer ergonomics — to agentic AI. It's designed as a thin, composable layer that handles the agent loop and model interaction while leaving infrastructure concerns (memory, deployment, observability) to the application. The dependency injection system is the core integration mechanism: you define typed dependencies that get injected into tool functions and system prompts at runtime.

#### Provider Support

**Excellent.** Model-agnostic with one of the broadest provider lists of any framework:
- OpenAI, Anthropic, Google Gemini, DeepSeek, Grok (xAI), Cohere, Mistral, Perplexity
- Azure OpenAI, AWS Bedrock, Google Vertex AI
- Ollama, LiteLLM (as a meta-provider for anything LiteLLM supports)
- Custom providers via well-defined interface

No provider is privileged. The model abstraction is clean and doesn't leak vendor-specific concepts.

#### MCP Support

**First-class.** Multiple integration paths:
- Native MCP client support (connect to any MCP server)
- MCP server exposure (expose Pydantic AI tools as MCP servers)
- FastMCP integration (direct compatibility with KAOS's existing FastMCP usage)
- Tool discovery and invocation via standard MCP protocol

This is the strongest MCP story of any evaluated framework.

#### Memory / State Management

**No built-in memory — by design.** Pydantic AI uses dependency injection for state management: you define a `Deps` type that carries whatever context your agent needs (database connections, session state, memory stores). This means:
- KAOS's RedisMemory integrates trivially as a dependency
- No framework memory abstraction to fight or work around
- No hidden LLM calls for memory management (unlike CrewAI)
- No vendor-locked memory backends (unlike ADK)

For KAOS, this is ideal. The framework has zero opinion on memory, which means zero conflict.

#### Observability

OpenTelemetry supported via Pydantic Logfire integration. Logfire is the "easy path" (Pydantic's commercial offering), but OTel backends are explicitly supported. Spans are emitted for agent runs, tool calls, and model interactions. KAOS can route these to its existing OTLP collector without adopting Logfire.

**Mild concern:** Logfire is promoted in docs, but OTel support is not an afterthought — it's architecturally supported.

#### Agent-to-Agent / A2A Protocol

**First-class A2A support via FastA2A.** FastA2A is a separate, framework-agnostic library (built on Starlette/ASGI) that implements the A2A protocol. Key properties:
- Framework-agnostic: works with Pydantic AI agents but also any ASGI-compatible agent
- Starlette-based: lightweight, production-ready ASGI server
- Pragmatic implementation: focuses on making A2A work, not over-abstracting it
- Compatible with KAOS's HTTP-based agent communication model

This is the most pragmatic A2A implementation evaluated. Unlike ADK's over-abstracted version, FastA2A is thin and flexible.

#### Extensibility

High. The dependency injection pattern means users can inject any custom logic into agents without modifying framework internals. The agent definition pattern (system prompt + tools + deps + result type) maps well to KAOS's model of user-defined custom agent images. Users building custom KAOS agents would define their agent using Pydantic AI's declarative API, which is simpler than the current custom agent code.

Also supports: graph-based workflows, durable execution, streaming, structured output validation.

#### Community

Small but high-quality. ~15K GitHub stars — the smallest of evaluated frameworks. However:
- Built by the Pydantic team, who maintain one of Python's most-used libraries
- Active development with frequent releases
- Growing adoption driven by Pydantic's existing reputation
- Community is focused on production use cases, not hype

#### KAOS Fit Assessment

**STRONG FIT.** Pydantic AI's design philosophy — thin, type-safe, bring-your-own-infrastructure — is exactly what KAOS needs. It replaces the agent loop and model interaction layer without touching memory, observability, deployment, or A2A communication. The dependency injection system provides a clean integration point for KAOS's existing Redis memory, OTel telemetry, and MCP tools. FastA2A is the most practical A2A implementation available.

**Risks:** Pre-1.0 API instability, smaller community for troubleshooting. Mitigated by the Pydantic team's track record and by wrapping framework APIs behind KAOS interfaces.

---

### 2. LangChain / LangGraph

| Attribute | Details |
|-----------|---------|
| **Version** | LangChain 0.3.x / LangGraph 0.x (evolving) |
| **License** | MIT |
| **GitHub Stars** | ~127K (LangChain) / ~25K (LangGraph) |
| **Maintainer** | LangChain Inc. |

#### Design Philosophy

LangChain started as a general-purpose LLM abstraction layer. After criticism of over-abstraction, the team created LangGraph as a lower-level orchestration framework focused on durable execution, stateful graphs, human-in-the-loop workflows, and streaming. Today, the recommended path is: LangGraph for orchestration, LangChain Core for model abstractions, and LangSmith for observability. The ecosystem is large but the "which package do I use?" confusion is real.

#### Provider Support

**Extensive.** LangChain has the broadest LLM provider integration ecosystem — dozens of providers via community-maintained packages. However, provider support comes through LangChain's own abstraction layer, which adds overhead compared to direct SDK usage or LiteLLM.

#### MCP Support

Present but adapted to fit LangChain's tool abstraction model. MCP tools are wrapped in LangChain's tool interface rather than used natively. This adds a translation layer between MCP's protocol and LangChain's internal representation.

#### Memory / State Management

**Sophisticated but abstracted.** LangGraph provides:
- **Short-term memory:** Thread-scoped checkpoints (conversation state persisted per thread)
- **Long-term memory:** Cross-session stores with custom namespaces via `BaseStore` interface
- `InMemoryStore` for prototyping, database-backed stores for production
- Redis is supported but through LangChain's checkpoint/store abstraction

The memory system works but adds abstraction layers over what could be direct Redis operations. For KAOS, this means replacing a simple RedisMemory with LangChain's more complex memory abstraction for no clear benefit.

#### Observability

**LangSmith (proprietary) is the primary observability path.** LangSmith provides tracing, evaluation, monitoring, and debugging. OTel integration exists but is not the default or recommended path. Using OTel with LangChain requires more setup than LangSmith and doesn't capture all framework-specific telemetry.

**This is a significant concern for KAOS.** KAOS requires OTel-native observability, not a vendor-specific alternative.

#### Agent-to-Agent / A2A Protocol

No explicit A2A protocol support found. Multi-agent orchestration exists within LangGraph (supervisor patterns, swarm patterns) but assumes agents are nodes in a single graph, not distributed services communicating over HTTP. This conflicts with KAOS's pod-per-agent model.

#### Extensibility

Mixed. The ecosystem is huge (hundreds of integrations) but the abstraction layers make custom extensions more complex than necessary. Users building custom KAOS agents would need to learn LangChain's concepts (chains, runnables, graphs, state) on top of KAOS's concepts. The learning curve is significant.

#### Community

**Largest community of any evaluated framework.** ~127K stars, thousands of tutorials, active StackOverflow presence. However:
- Significant portion of community knowledge references outdated APIs (chains → LCEL → LangGraph)
- Two major paradigm shifts have left fragmented documentation
- The "LangChain fatigue" sentiment is real in the community

#### KAOS Fit Assessment

**POOR FIT.** LangChain/LangGraph's design philosophy conflicts with KAOS at multiple levels:
1. **Runtime ownership:** LangGraph assumes it manages the runtime (durable execution, checkpointing). KAOS's K8s operator manages the runtime.
2. **Memory abstraction:** LangChain wants to own memory through its abstraction layer. KAOS has simpler, working Redis memory.
3. **Observability vendor lock:** LangSmith push conflicts with KAOS's OTel requirement.
4. **Dependency bloat:** LangChain pulls hundreds of transitive dependencies, bloating container images.
5. **Over-abstraction:** Simple operations become complex chain/graph definitions.

LangGraph's graph-based state machines are genuinely powerful for complex workflows, but KAOS's agent model (agent loop + tools + memory) doesn't need graph-based orchestration at the data-plane level. The orchestration in KAOS happens at the K8s operator level, not within the agent.

---

### 3. CrewAI

| Attribute | Details |
|-----------|---------|
| **Version** | Established (2023+, active development) |
| **License** | MIT (core) / Commercial (Enterprise) |
| **GitHub Stars** | ~44K |
| **Maintainer** | CrewAI Inc. |

#### Design Philosophy

CrewAI is built around the metaphor of a "crew" of agents working together. Each agent has a Role, Goal, and Backstory. Agents are organized into Crews that execute Tasks in sequential or hierarchical processes. The framework emphasizes ease of use for multi-agent systems with built-in memory, planning, and delegation.

#### Provider Support

Provider-agnostic via LLM configuration. Supports OpenAI, Anthropic, and others through standard configuration. Not as extensive as LangChain or Pydantic AI's provider lists, but adequate.

#### MCP Support

No explicit MCP support found in official documentation. CrewAI has its own tool system (custom tools, LangChain tool adapters). MCP integration would require custom adapter code.

#### Memory / State Management

**Sophisticated but problematic for KAOS:**
- Unified Memory class with LLM-powered analysis of what to remember
- Hierarchical scopes (short-term, long-term, entity-based, user-specific)
- Composite scoring (semantic similarity + recency + importance)
- **Default storage: LanceDB** (local file-based) — not distributed
- Custom backends possible via `StorageBackend` protocol

**Critical issue:** Memory save/recall triggers additional LLM calls for semantic analysis. This adds hidden latency and cost that KAOS's simple session-based memory doesn't have. The LanceDB default is local and not suitable for distributed K8s pods.

#### Observability

Limited. No native OTel integration found. CrewAI has logging and some tracing capabilities, but not at the level KAOS requires.

#### Agent-to-Agent / A2A Protocol

Multi-agent by design (agents, crews, flows), but communication is within a single process, not across distributed services. No A2A protocol support found. Agent delegation happens through CrewAI's internal orchestration, not HTTP-based communication.

#### Extensibility

The Role/Goal/Backstory pattern is opinionated. It works well for "team of agents" use cases but is more restrictive than KAOS's flexible agent model. Users building custom agents must fit the CrewAI mental model. Enterprise features (deployment, triggers, team management) are behind a commercial tier.

#### Community

Large and active (~44K stars). Strong adoption in the "AI agents" space. Good documentation and tutorials. However, most community usage is for the "team of agents" pattern — KAOS's distributed orchestration pattern is less represented.

#### KAOS Fit Assessment

**POOR FIT.** Multiple conflicts:
1. **Memory system mismatch:** LLM-powered memory analysis adds cost and latency vs. KAOS's simple Redis sessions. LanceDB default is not distributed.
2. **Process model conflict:** CrewAI assumes agents run in the same process. KAOS runs agents in separate K8s pods.
3. **Opinionated agent model:** Role/Goal/Backstory pattern doesn't map to all KAOS agent types.
4. **Enterprise tier gating:** Key features behind paywall conflicts with KAOS being open-source.
5. **No MCP support:** Would need custom integration for KAOS's MCP tool system.
6. **No A2A protocol:** Distributed agent communication not supported.

---

### 4. Google ADK (Agent Development Kit)

| Attribute | Details |
|-----------|---------|
| **Version** | v0.5.0+ (young, multi-language: Python, TS, Go, Java) |
| **License** | Apache 2.0 |
| **GitHub Stars** | ~18K |
| **Maintainer** | Google |

#### Design Philosophy

Google ADK positions itself as a model-agnostic, multi-language framework for building AI agents. It supports Gemini (optimized), Claude, Vertex AI models, Ollama, vLLM, and LiteLLM. The framework includes tool support, A2A protocol support, and memory services. However, the production-grade implementations consistently point to GCP services.

#### Provider Support

Claims model-agnostic. Supports Gemini (optimized), Claude, Vertex AI, Ollama, vLLM, LiteLLM. In practice, Gemini is the most thoroughly tested and documented path. Other providers work but are second-class.

#### MCP Support

**Built-in.** MCP tools are a supported tool type. Agents can connect to MCP servers and use MCP tools natively. Good implementation.

#### Memory / State Management

**This is the confirmed deal-breaker:**
- `InMemoryMemoryService` — ephemeral, in-process only. Suitable for prototyping.
- `VertexAiMemoryBankService` — persistent, distributed. **Requires Google Cloud Vertex AI.**
- No Redis backend. No pluggable memory interface for third-party backends.

For KAOS, this means: no persistent distributed memory without GCP. The KAOS team's rejection of ADK was correct.

Similarly, session management offers `InMemorySessionService` for prototyping and Vertex AI-backed services for production.

#### Observability

Logging-based. No native OTel integration found in documentation. Google Cloud's observability tools (Cloud Monitoring, Cloud Trace) are the assumed production path.

#### Agent-to-Agent / A2A Protocol

**Full A2A protocol support** — both exposing agents as A2A endpoints and consuming other A2A agents. However, KAOS's experience was that the implementation is over-abstracted and inflexible. The protocol works, but the framework's A2A layer adds unnecessary complexity compared to direct HTTP communication.

#### Extensibility

Multi-language support (Python, TypeScript, Go, Java) is unique. Extension points exist for custom tools, models, and callbacks. However, extending memory or sessions beyond GCP services requires working against the framework's assumptions.

#### Community

Growing (~18K stars, young framework). Multi-language support expands potential community. Google's backing ensures continued development, but also ensures continued GCP alignment.

#### KAOS Fit Assessment

**REJECTED — CONFIRMED.** The KAOS team's prior rejection is validated by the documentation:
1. **Memory is GCP-locked.** No path to Redis-backed distributed memory without building a custom `MemoryService` implementation.
2. **Deployment assumes GCP.** Docs focus on Agent Engine, Cloud Run, GKE.
3. **A2A is over-abstracted.** Protocol works but the implementation is inflexible.
4. **Observability assumes GCP.** No OTel path.

ADK is a GCP distribution channel. Open-source surface, cloud-locked internals.

---

### 5. Microsoft AutoGen

| Attribute | Details |
|-----------|---------|
| **Version** | 0.4+ (stable post-rewrite) |
| **License** | MIT |
| **GitHub Stars** | ~55K |
| **Maintainer** | Microsoft Research |

#### Design Philosophy

AutoGen underwent a major rewrite from 0.2 to 0.4+. The new architecture has three layers:
- **Core:** Event-driven, scalable multi-agent runtime (foundational messaging system)
- **AgentChat:** High-level conversational patterns (teams, group chat, handoffs)
- **Extensions:** MCP support, Docker code execution, external integrations

The design emphasizes multi-agent conversation patterns — agents communicating in structured ways (round-robin, selector-based, swarm). AutoGen Studio provides a web UI for no-code prototyping.

#### Provider Support

Supports OpenAI, Azure OpenAI, and others via model client abstraction. Azure is the most thoroughly documented path. Other providers work via OpenAI-compatible endpoints. Not as broad as Pydantic AI or LangChain.

#### MCP Support

**Supported via `McpWorkbench` extension.** MCP servers can be connected and tools exposed to agents. The integration is through AutoGen's extension system rather than native to the core.

#### Memory / State Management

AutoGen's state management focuses on conversation history within agent runtimes. The `GrpcWorkerAgentRuntime` supports distributed agent communication via gRPC. However:
- No built-in distributed memory store (like Redis-backed sessions)
- State is managed at the runtime level, not as a pluggable memory interface
- Distributed patterns use gRPC, not HTTP — conflicts with KAOS's HTTP-based communication

#### Observability

Limited OTel integration found. AutoGen has logging and event tracing for debugging, but native OTel support (traces, metrics, logs to OTLP) is not a documented first-class feature.

#### Agent-to-Agent / A2A Protocol

**Strong multi-agent focus, but gRPC-based.** The `GrpcWorkerAgentRuntime` enables distributed agent communication across processes/machines. However:
- Uses gRPC, not HTTP — different protocol than KAOS's A2A approach
- No A2A protocol (Google's A2A spec) support found
- The distributed runtime model assumes AutoGen manages the topology, not an external orchestrator (K8s operator)

#### Extensibility

Modular extension system. Docker code execution is a useful feature for sandboxed agent actions. Multi-package architecture (core, agentchat, extensions) allows selective adoption. However, the multi-package complexity creates confusion about which packages to use.

#### Community

Large (~55K stars). However, the major rewrite means most community content references the old 0.2 API. Current documentation is the only reliable source. StackOverflow answers are frequently outdated.

#### KAOS Fit Assessment

**POOR FIT.** Several conflicts:
1. **gRPC vs HTTP:** AutoGen's distributed runtime uses gRPC. KAOS uses HTTP-based agent communication. Significant protocol mismatch.
2. **Runtime ownership:** AutoGen's runtime model assumes AutoGen manages agent topology and communication, conflicting with KAOS's K8s operator.
3. **Post-rewrite instability:** The recent major rewrite means APIs may still be settling.
4. **Azure ecosystem gravity:** Documentation defaults to Azure patterns.
5. **No A2A protocol:** Distributed communication exists but via gRPC, not A2A.

The gRPC-based distributed runtime is AutoGen's biggest differentiator but also its biggest incompatibility with KAOS.

---

### 6. Microsoft Semantic Kernel

| Attribute | Details |
|-----------|---------|
| **Version** | 1.0+ (stable, non-breaking changes commitment) |
| **License** | MIT |
| **GitHub Stars** | ~27K |
| **Maintainer** | Microsoft |

#### Design Philosophy

Semantic Kernel is lightweight AI middleware designed for enterprise applications. It provides a kernel (central orchestration layer) that connects AI models, plugins (tools), and memory. The architecture emphasizes composability — kernels, planners, plugins, and filters. The Agent Framework adds ChatCompletionAgent, OpenAIAssistantAgent, and multi-agent orchestration.

#### Provider Support

Supports OpenAI, Azure OpenAI, Google Gemini, Hugging Face, Ollama, and others. Azure OpenAI is the most thoroughly documented and tested path. Other providers work but documentation quality varies.

#### MCP Support

Not found as a first-class feature. Semantic Kernel uses a plugin system based on OpenAPI specifications. MCP tools would need adaptation through a plugin wrapper. The OpenAPI-based plugin model is different from MCP's protocol.

#### Memory / State Management

Memory capabilities exist but many Python features are marked "Experimental":
- Semantic memory with embeddings and vector stores
- Chat history management
- Various vector store integrations

"Experimental" status means these APIs can change or be removed without notice. For KAOS's requirement of stable distributed memory, this is a risk.

#### Observability

**Best enterprise telemetry story.** Semantic Kernel has hooks and filters that emit telemetry events. OTel-compatible instrumentation is supported through the kernel's event system. Azure Monitor is the default destination, but OTel backends are architecturally supported.

#### Agent-to-Agent / A2A Protocol

Multi-agent orchestration package exists with agent coordination patterns. However, this is within-process orchestration, not distributed agent communication. No A2A protocol support found.

#### Extensibility

Plugin-based extensibility is well-designed. OpenAPI-based plugin discovery allows agents to use any service with an OpenAPI spec as a tool. Filters and hooks provide middleware-style extensibility for cross-cutting concerns. The middleware pattern is enterprise-friendly.

#### Community

Medium (~27K stars). Strong in the .NET/C# ecosystem. Python community is smaller and less active. Enterprise adoption is the primary driver.

#### KAOS Fit Assessment

**MODERATE FIT — BUT WRONG FOCUS.** Semantic Kernel is well-engineered middleware, but:
1. **C# first, Python second:** Python features lag and many are "Experimental."
2. **Plugin model differs from MCP:** OpenAPI-based plugins ≠ MCP tools. Would need adaptation.
3. **Azure gravity:** Documentation defaults to Azure OpenAI and Azure services.
4. **Not an agent orchestration framework:** Agent capabilities are bolted onto a middleware kernel, not the core mission.
5. **Enterprise complexity:** Designed for enterprise patterns that may be overkill for KAOS's agent model.

The OTel-compatible telemetry and middleware pattern are genuinely good, but the Python-second status and Azure gravity are disqualifying for KAOS.

---

### 7. LlamaIndex

| Attribute | Details |
|-----------|---------|
| **Version** | Established (0.10.x+, active development) |
| **License** | MIT |
| **GitHub Stars** | ~47K |
| **Maintainer** | LlamaIndex Inc. |

#### Design Philosophy

LlamaIndex is primarily a **data/RAG framework** — connecting LLMs to data sources through indexing, retrieval, and synthesis. Agent capabilities (LlamaAgents, workflows) are a secondary capability added to the core RAG platform. The framework excels at document processing, embedding, vector search, and retrieval-augmented generation.

#### Provider Support

**Extensive.** Dozens of LLM providers through integration packages (OpenAI, Anthropic, Gemini, Cohere, Mistral, Ollama, and many more). Equally extensive embedding model support. The integration ecosystem is one of the largest.

#### MCP Support

**Present.** Dedicated MCP module for:
- Using MCP tools within LlamaIndex agents
- Converting LlamaIndex tools to MCP servers
- Bidirectional MCP integration

#### Memory / State Management

LlamaIndex's memory is RAG-centric — it excels at indexing and retrieving documents, not session-based conversation memory. Chat memory exists but is secondary to the retrieval system. For KAOS's session-based Redis memory, LlamaIndex's memory model is a paradigm mismatch.

#### Observability

Instrumentation module exists with callbacks and event handlers. LlamaCloud offers managed observability. OTel integration is possible but not the primary path. Observability focus is on RAG pipeline tracing (indexing, retrieval, synthesis), not agent orchestration tracing.

#### Agent-to-Agent / A2A Protocol

LlamaAgents supports deploying agents as servers (via `llamactl`). Workflow-based agent orchestration exists. However, no A2A protocol support found. The deployment model (llamactl) assumes LlamaIndex manages the agent lifecycle, which conflicts with KAOS's K8s operator.

#### Extensibility

Massive integration ecosystem — hundreds of data connectors, LLM providers, embedding models, vector stores. Users can build custom agents using LlamaIndex's workflow API. However, the extensibility is RAG-centric. Extending agent orchestration capabilities requires working within LlamaIndex's data-oriented worldview.

#### Community

Large (~47K stars). Very active in the RAG space. Extensive tutorials and examples. However, community expertise is overwhelmingly RAG-focused — agent orchestration questions get less attention.

#### KAOS Fit Assessment

**POOR FIT — PARADIGM MISMATCH.** LlamaIndex is excellent at what it does (RAG), but KAOS is an agent orchestration platform, not a RAG platform:
1. **RAG-centric worldview:** Everything is viewed through indexing/retrieval. Agent orchestration is secondary.
2. **Memory model mismatch:** RAG memory ≠ session-based agent memory.
3. **Deployment model conflict:** LlamaAgents' deployment model (llamactl) conflicts with K8s operator.
4. **Surface area bloat:** Pulling in LlamaIndex brings massive RAG infrastructure that KAOS doesn't need.
5. **LlamaCloud push:** Commercial offering creates vendor gravity.

LlamaIndex could be useful **within** individual KAOS agents that need RAG capabilities, but it should not be the framework foundation.

---

### 8. Haystack (deepset)

| Attribute | Details |
|-----------|---------|
| **Version** | 2.24 (stable; v2.25-unstable available) |
| **License** | Apache 2.0 |
| **GitHub Stars** | ~24K |
| **Maintainer** | deepset GmbH |

#### Design Philosophy

Haystack is a pipeline-based framework for building AI applications. Components (generators, retrievers, converters, agents) are connected into pipelines that process data step by step. The v2 rewrite (from v1) introduced a clean, modular component model with strong typing. The framework emphasizes reliability, testability, and composability.

#### Provider Support

Good. Supports OpenAI, Anthropic, Google, Cohere, Mistral, Ollama, and others via generator components. Each provider has a dedicated component package. Not as extensive as LangChain or LlamaIndex, but covers major providers.

#### MCP Support

No explicit MCP support found in documentation. Haystack has its own tool system for the Agent component, but MCP protocol integration would require custom implementation.

#### Memory / State Management

Pipeline-based state management. The Agent component has a `state_schema` that persists across the agent loop. However:
- No built-in distributed memory
- State is pipeline-scoped, not session-scoped across requests
- No Redis backend for persistent session memory

For KAOS, Haystack's state model doesn't address the distributed session memory requirement.

#### Observability

Pipeline tracing exists for debugging. Specific OTel integration not found as a first-class feature. deepset Cloud provides commercial observability, but self-hosted OTel integration is not well-documented.

#### Agent-to-Agent / A2A Protocol

Multi-agent via `ComponentTool` — wrapping agents as tools for coordinator agents. This is within-process composition, not distributed agent communication. No A2A protocol support.

#### Extensibility

Clean component model. Building custom components is straightforward (implement the `@component` decorator with `run()` method). The modular design makes it easy to add new generators, retrievers, or processors. However, the pipeline model is restrictive for non-pipeline use cases.

#### Community

Smaller (~24K stars) but dedicated. Quality community with focus on production NLP/AI pipelines. Less hype-driven than LangChain or CrewAI. Good documentation quality.

#### KAOS Fit Assessment

**NEUTRAL — INSUFFICIENT VALUE.** Haystack is well-engineered but doesn't solve KAOS's problems:
1. **Pipeline model mismatch:** KAOS's agent loop ≠ pipeline processing.
2. **No distributed memory:** Doesn't address Redis session memory.
3. **No A2A support:** Distributed agent communication not supported.
4. **No MCP support:** Would need custom integration.
5. **Clean but insufficient:** Good engineering, but you'd write as much custom code with Haystack as without it.

If KAOS needed NLP pipelines (document processing, retrieval), Haystack would be excellent. For agent orchestration, it adds little value.

---

### 9. DSPy (Stanford NLP)

| Attribute | Details |
|-----------|---------|
| **Version** | Established (active development, 250+ contributors) |
| **License** | MIT |
| **GitHub Stars** | ~32K |
| **Maintainer** | Stanford NLP Group |

#### Design Philosophy

DSPy's philosophy is unique: **"Programming, not prompting, LMs."** Instead of manually crafting prompts, you define typed signatures (input/output schemas) and modules (Predict, ChainOfThought, ReAct, CodeAct). DSPy's **optimizers** then automatically compile programs into effective prompts or fine-tuned weights by running training examples through the pipeline and optimizing for a metric.

This is fundamentally different from every other framework — DSPy optimizes *how* agents interact with LLMs, not *how* agents are orchestrated.

#### Provider Support

**Excellent via LiteLLM.** DSPy uses LiteLLM internally, which means it supports every provider LiteLLM supports (dozens). This aligns with KAOS's existing LiteLLM usage.

#### MCP Support

**Present.** DSPy has a dedicated MCP tutorial and programming module for connecting to MCP servers and using MCP tools within DSPy programs.

#### Memory / State Management

No built-in distributed memory. DSPy manages LLM interaction history within program execution but doesn't provide session-based memory across requests. Memory is not DSPy's concern — it's focused on the LLM interaction quality, not infrastructure.

#### Observability

No built-in OTel support. DSPy provides inspection and debugging tools for understanding how optimizers modify prompts, but production observability (traces, metrics, logs to OTLP) is not a feature.

#### Agent-to-Agent / A2A Protocol

No A2A support. DSPy is not an agent orchestration framework — it's a prompt/program optimization framework. Multi-agent communication is outside its scope.

#### Extensibility

Highly extensible within its paradigm. Custom modules, metrics, optimizers, and assertions can be defined. The programming model is expressive and composable. However, extending DSPy to handle orchestration concerns (distributed communication, memory, deployment) is working against its design.

#### Community

Active research community (~32K stars, 250+ contributors). Strong academic backing (Stanford NLP). Growing production adoption as teams discover the value of programmatic prompt optimization. However, community expertise is optimization-focused, not orchestration-focused.

#### KAOS Fit Assessment

**WRONG TOOL FOR THE JOB.** DSPy is excellent at what it does (LLM program optimization) but solves a completely different problem than KAOS:
1. **Paradigm mismatch:** DSPy optimizes prompts/weights. KAOS orchestrates distributed agents.
2. **No orchestration:** No multi-agent, no distributed communication, no deployment model.
3. **No infrastructure:** No memory, no observability, no A2A.

**However:** DSPy could be valuable **within** KAOS agents for prompt optimization. Consider offering DSPy as an optional tool/library in KAOS's agent SDK, not as the framework foundation.

---

## Comparison Matrix

| Dimension | Pydantic AI | LangChain/LangGraph | CrewAI | Google ADK | AutoGen | Semantic Kernel | LlamaIndex | Haystack | DSPy |
|-----------|-------------|---------------------|--------|------------|---------|-----------------|------------|----------|------|
| **Provider Agnosticism** | ✅ Excellent | ✅ Extensive | ⚠️ Good | ⚠️ Gemini-first | ⚠️ Azure-first | ⚠️ Azure-first | ✅ Extensive | ✅ Good | ✅ LiteLLM |
| **MCP Support** | ✅ Native + FastMCP | ⚠️ Adapted | ❌ None found | ✅ Built-in | ⚠️ Extension | ❌ Plugin model | ✅ Module | ❌ None found | ✅ Module |
| **Distributed Memory** | ✅ BYO (ideal) | ⚠️ Abstracted Redis | ❌ LanceDB local | ❌ GCP-locked | ❌ Not built-in | ⚠️ Experimental | ❌ RAG-centric | ❌ Not built-in | ❌ Not applicable |
| **OTel Observability** | ✅ Supported | ⚠️ LangSmith push | ❌ Limited | ❌ GCP-native | ❌ Limited | ⚠️ OTel-compatible | ⚠️ Callbacks | ❌ Limited | ❌ None |
| **A2A Protocol** | ✅ FastA2A | ❌ None | ❌ None | ⚠️ Over-abstracted | ❌ gRPC only | ❌ None | ❌ None | ❌ None | ❌ None |
| **K8s Deployment Fit** | ✅ Library in pod | ❌ Owns runtime | ⚠️ Process-bound | ❌ GCP deploy | ❌ Owns runtime | ⚠️ Middleware | ❌ llamactl | ⚠️ Pipeline | ❌ No deploy model |
| **User Extensibility** | ✅ DI + decorators | ⚠️ Complex APIs | ⚠️ Opinionated | ⚠️ GCP patterns | ⚠️ Multi-package | ⚠️ Plugin system | ⚠️ RAG-oriented | ✅ Component model | ✅ Module system |
| **API Stability** | ⚠️ Pre-1.0 | ❌ Major churn | ⚠️ Evolving | ⚠️ Young | ❌ Post-rewrite | ⚠️ Experimental flags | ⚠️ Evolving | ✅ Post-v2 stable | ⚠️ Evolving |
| **Community Size** | Small (15K) | Huge (127K/25K) | Large (44K) | Medium (18K) | Large (55K) | Medium (27K) | Large (47K) | Small (24K) | Medium (32K) |
| **License** | MIT | MIT | MIT/Commercial | Apache 2.0 | MIT | MIT | MIT | Apache 2.0 | MIT |
| **Vendor Lock-in Risk** | LOW (Logfire mild) | MEDIUM (LangSmith) | MEDIUM (Enterprise) | CRITICAL (GCP) | MEDIUM (Azure) | MEDIUM (Azure) | MEDIUM (LlamaCloud) | LOW (deepset) | LOW (academic) |
| **Escape Difficulty** | Easy | Hard | Medium | Hard | Medium | Easy-Medium | Medium | Easy-Medium | Easy |
| **KAOS Fit** | **STRONG** | POOR | POOR | REJECTED | POOR | MODERATE | POOR | NEUTRAL | WRONG TOOL |

### Legend
- ✅ = Strong fit / well-supported
- ⚠️ = Partial / requires work or has concerns
- ❌ = Poor fit / not supported / significant issues

---

## Recommendations for KAOS

### Top Contenders

#### 1. Pydantic AI (RECOMMENDED)

**Why:** Pydantic AI is the only framework whose design philosophy — thin layer, type-safe, bring-your-own-everything — aligns with KAOS's architecture. It replaces the right things (agent loop, model interaction) and leaves the right things alone (memory, observability, deployment, A2A).

**What KAOS gets:**
- Cleaner agent definition API (typed deps, structured output, declarative tools)
- First-class MCP support compatible with existing FastMCP usage
- Pragmatic A2A implementation (FastA2A) that doesn't over-abstract
- OTel-compatible observability
- Dependency injection for clean Redis memory integration
- Smaller, more maintainable agent code (replaces the ~993-line client.py)

**What KAOS keeps:**
- RedisMemory (injected as dependency)
- OTel telemetry (framework emits spans, KAOS routes to OTLP)
- K8s operator deployment model (framework is a library in the pod)
- FastMCP tool integration (directly compatible)
- HTTP-based A2A communication (FastA2A enhances, doesn't replace)
- LiteLLM model routing (Pydantic AI supports LiteLLM as a provider)

**Risks to mitigate:**
- Pre-1.0 API instability → Pin versions, wrap behind KAOS interfaces
- Smaller community → Offset by Pydantic team's track record and high code quality
- Logfire push → Use OTel directly, don't adopt Logfire

**Confidence:** HIGH — Based on thorough documentation analysis. Pydantic AI's design is architecturally compatible with KAOS.

#### 2. Stay Custom + Targeted Libraries (VIABLE ALTERNATIVE)

**Why:** KAOS's custom code works. The complexity hotspots (client.py, memory.py, server.py) are maintainable. If Pydantic AI's pre-1.0 status is too risky, staying custom and adopting targeted libraries is a defensible choice.

**What to adopt:**
- **FastA2A** (Pydantic team's A2A library) — framework-agnostic, works without Pydantic AI
- **DSPy** (optional) — offer as a library for prompt optimization within agents
- **Pydantic** (already likely in use) — for agent configuration validation

**When to reconsider Pydantic AI:**
- When it reaches 1.0 with stable APIs
- When community grows and patterns are well-established
- When KAOS's custom code maintenance becomes a burden

**Confidence:** HIGH — This is the safe choice with no framework risk.

### Frameworks to Avoid

| Framework | Verdict | Primary Reason |
|-----------|---------|----------------|
| **Google ADK** | REJECT | GCP vendor lock-in confirmed (memory, deployment, observability). Already rejected by team. |
| **LangChain/LangGraph** | AVOID | Over-abstraction, runtime ownership conflict, LangSmith vendor push, dependency bloat, API instability history. |
| **CrewAI** | AVOID | Memory system adds hidden LLM costs, LanceDB not distributed, opinionated agent model, no MCP/A2A, Enterprise gating. |
| **AutoGen** | AVOID | gRPC-based distributed model conflicts with HTTP-based KAOS, runtime ownership conflict, post-rewrite instability, Azure gravity. |
| **LlamaIndex** | AVOID (as foundation) | RAG framework doing agents — paradigm mismatch. Useful within agents for RAG, not as the platform framework. |
| **DSPy** | AVOID (as foundation) | Solves prompt optimization, not agent orchestration. Useful within agents as a library, not as the framework. |
| **Semantic Kernel** | AVOID | Python is second-class (many features Experimental), Azure gravity, not designed for agent orchestration. |
| **Haystack** | AVOID | Well-engineered but insufficient value — doesn't solve KAOS's specific problems (memory, A2A, deployment). |

### Key Tradeoffs

| Tradeoff | Pydantic AI | Stay Custom |
|----------|-------------|-------------|
| **Agent code complexity** | Lower — cleaner API, typed deps | Higher — current ~993-line client.py |
| **API stability risk** | Pre-1.0 risk | Full control |
| **MCP integration** | Enhanced (native support + FastMCP) | Current (FastMCP only, works fine) |
| **A2A capabilities** | Enhanced (FastA2A) | Current (HTTP-based, works fine) |
| **User extensibility** | Better DX (declarative agent definition) | Current (users extend Python classes) |
| **Maintenance burden** | Lower (framework handles agent loop) | Higher (maintain custom loop) |
| **Upgrade risk** | Framework version changes | Only dependency upgrades |
| **Community support** | Growing but small | Self-supported |
| **Time to adopt** | 2-4 weeks for core migration | Zero |

### Decision Framework

**Adopt Pydantic AI if:**
- The team values cleaner agent APIs and developer experience
- MCP and A2A capabilities need enhancement
- Maintenance burden of custom code is a real concern
- The team is comfortable with pre-1.0 framework risk (mitigated by interface wrapping)

**Stay custom if:**
- Stability is the top priority
- The custom code complexity is manageable
- The team prefers full control over all agent internals
- Pre-1.0 framework risk is unacceptable

**Hybrid approach (recommended):**
1. Adopt **FastA2A** (Pydantic team, framework-agnostic) for A2A communication — low risk, high value
2. Prototype one KAOS agent with **Pydantic AI** to validate the integration
3. If the prototype succeeds, migrate the agent loop incrementally
4. Keep RedisMemory, OTel telemetry, K8s operator, and FastMCP unchanged throughout

---

## Installation (Pydantic AI Path)

```bash
# Core framework
pip install pydantic-ai

# A2A support
pip install fasta2a

# Existing KAOS dependencies (unchanged)
pip install fastmcp          # MCP tool integration (already in use)
pip install litellm          # Model routing (already in use)
pip install opentelemetry-api opentelemetry-sdk  # OTel (already in use)
pip install redis             # Distributed memory (already in use)
```

---

## Sources

| Source | Type | Confidence |
|--------|------|------------|
| Pydantic AI official docs (ai.pydantic.dev) | Official Documentation | HIGH |
| Pydantic AI MCP docs | Official Documentation | HIGH |
| Pydantic AI A2A / FastA2A docs | Official Documentation | HIGH |
| LangGraph docs (docs.langchain.com) | Official Documentation | HIGH |
| LangGraph memory overview | Official Documentation | HIGH |
| CrewAI official docs (docs.crewai.com) | Official Documentation | HIGH |
| CrewAI memory documentation | Official Documentation | HIGH |
| Google ADK docs (google.github.io/adk-docs) | Official Documentation | HIGH |
| Google ADK memory service docs | Official Documentation | HIGH |
| Google ADK A2A documentation | Official Documentation | HIGH |
| AutoGen stable docs (microsoft.github.io/autogen) | Official Documentation | HIGH |
| Semantic Kernel overview (learn.microsoft.com) | Official Documentation | HIGH |
| Semantic Kernel agent framework docs | Official Documentation | HIGH |
| LlamaIndex official docs (docs.llamaindex.ai) | Official Documentation | HIGH |
| Haystack intro docs (docs.haystack.deepset.ai) | Official Documentation | HIGH |
| Haystack agent component docs | Official Documentation | HIGH |
| DSPy official docs (dspy.ai) | Official Documentation | HIGH |
| KAOS PROJECT.md | Internal | HIGH |
| KAOS team ADK rejection experience | Internal (team knowledge) | HIGH |
| GitHub star counts (all frameworks) | GitHub | MEDIUM (point-in-time) |

---

*Researched 2026-02-20. All findings based on official documentation fetched and analyzed during research session. Confidence is HIGH for framework capabilities (verified from docs) and MEDIUM-HIGH for risk assessments (based on documentation analysis + community patterns).*
