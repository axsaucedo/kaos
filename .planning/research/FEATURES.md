# Feature Landscape: Agentic AI Frameworks vs KAOS

**Domain:** Agentic AI Frameworks
**Researched:** 2026-02-20
**Overall Confidence:** MEDIUM-HIGH (based on official documentation review of all 9 frameworks)

---

## KAOS Current Capabilities (Baseline)

| Dimension | Current State |
|-----------|--------------|
| **Agentic Loop** | Two-phase execution (tool loop → final response), native function calling + string-parsed tool calls |
| **Memory & State** | LocalMemory (in-process dict), RedisMemory (distributed, session-scoped), NullMemory (stateless), max_messages truncation |
| **MCP Tools** | FastMCP SDK integration, Streamable HTTP transport, lazy connection with auto-retry |
| **Model Routing** | LiteLLM for provider-agnostic LLM access |
| **Observability** | OpenTelemetry with OTLP export (traces, metrics, logs), auto-instrumentation of FastAPI and httpx, custom spans |
| **A2A Communication** | Agent-to-agent delegation via `/v1/chat/completions`, peer discovery via env vars, dynamic tool registration, A2A discovery at `/.well-known/agent` |
| **Streaming** | SSE streaming for final responses |
| **HTTP API** | OpenAI-compatible `/v1/chat/completions` endpoint |
| **Custom Images** | Users can build own container images |

---

## Per-Framework Feature Analysis

---

### 1. Pydantic AI

**Overall assessment:** Strongest direct competitor to KAOS's design philosophy. Type-safe, Pythonic, minimal abstraction. The closest in spirit but more mature in several dimensions.

#### Memory & State
No built-in distributed memory abstraction. State is passed via dependency injection — a `deps` object flows through agent runs. Conversation history is managed manually: `result.all_messages()` is captured and passed back into subsequent `agent.run()` calls. No Redis or distributed memory out of the box. Users must build their own persistence layer.

**Confidence:** HIGH (verified via official docs)

#### MCP Support
Excellent. Three native integration methods:
1. **Direct `MCPServer`** — wrap any MCP server for use as a tool source
2. **`FastMCPToolset`** — use FastMCP's Client class for richer control
3. **Provider built-in MCP** — e.g., Anthropic's native MCP support passed through

Can also expose Pydantic AI agents AS MCP servers. Full bidirectional MCP story.

**Confidence:** HIGH (verified via official MCP docs page)

#### Observability
Outstanding OpenTelemetry support. Pydantic Logfire is the commercial offering, but the framework fully supports any OTel backend — you can use raw OTel SDK without Logfire. Follows GenAI semantic conventions. Multiple instrumentation API versions (v1–v4) for forward compatibility. Traces include tool calls, model interactions, retry logic.

**Confidence:** HIGH (verified via Logfire + observability docs)

#### A2A / Multi-Agent Communication
Full A2A protocol support via the `FastA2A` library (Starlette-based ASGI app). Convenience method: `agent.to_a2a()` creates an A2A-compliant server. Supports task storage, context storage, brokers, and workers. Can discover and call remote agents via standard A2A protocol.

**Confidence:** HIGH (verified via A2A docs page)

#### Model Routing
Extremely broad native support: OpenAI, Anthropic, Gemini, Bedrock, Cohere, Mistral, xAI, Groq, HuggingFace, and more. ALSO supports LiteLLM and Ollama as OpenAI-compatible providers. Unique features: `FallbackModel` for automatic failover across providers, `ConcurrencyLimitedModel` for rate limiting.

**Confidence:** HIGH (verified via models docs)

#### Streaming
Supports streamed structured outputs with immediate validation. Streaming is first-class, not bolted on.

**Confidence:** HIGH

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | Pydantic AI Advantage |
|-----------|---------------|----------------------|
| Memory | RedisMemory for distributed state, memory abstraction layer | Dependency injection is more flexible for custom state |
| MCP | Comparable — both use FastMCP | Can expose agents AS MCP servers |
| Observability | Comparable — both native OTel | Logfire commercial offering adds value; GenAI semantic conventions |
| A2A | OpenAI-compatible endpoint is simpler | Full A2A protocol with task/context storage, brokers, workers |
| Models | LiteLLM (same) | Native provider SDKs + FallbackModel + ConcurrencyLimitedModel |
| Streaming | Comparable | Streamed structured outputs with validation |
| **Unique gaps** | — | Type-safe deps injection, structured output validation, graph support, durable execution, human-in-the-loop tool approval, evals framework |

---

### 2. LangChain / LangGraph

**Overall assessment:** The 800-pound gorilla. Massive ecosystem, massive complexity. LangGraph adds durable execution and stateful graphs. Not a philosophy match for KAOS (too much abstraction) but sets market expectations.

#### Memory & State
LangGraph provides checkpointing/persistence for graph state. Supports SQLite, PostgreSQL, and custom backends. Thread-scoped conversation memory with automatic state persistence between graph steps. LangChain itself has memory modules but they're being deprecated in favor of LangGraph's approach.

**Confidence:** MEDIUM (based on docs overview, not deep-dived)

#### MCP Support
Documented MCP integration. Can use MCP servers as tool sources in chains and graphs.

**Confidence:** MEDIUM (confirmed existence, not deep-dived)

#### Observability
LangSmith is the commercial tracing/debugging platform. NOT natively OpenTelemetry — uses a proprietary tracing format. You can export to OTel via adapters but it's not first-class. LangSmith is excellent for debugging chains but creates vendor lock-in.

**Confidence:** MEDIUM (known from ecosystem, not verified against latest docs)

#### A2A / Multi-Agent Communication
Multi-agent orchestration via LangGraph's graph primitives. Agents are nodes in a graph, communication happens via state passing. No native A2A protocol support — agents don't communicate over HTTP boundaries. LangGraph Platform (commercial) adds deployment and scaling.

**Confidence:** MEDIUM

#### Model Routing
Very broad provider support via the integrations ecosystem. Has LiteLLM integration. Hundreds of model provider packages.

**Confidence:** HIGH (well-known)

#### Streaming
Supports streaming in chains and graphs. "Deep Agents" concept adds auto-compression and subagent-spawning with virtual filesystems.

**Confidence:** MEDIUM

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | LangChain/LangGraph Advantage |
|-----------|---------------|-------------------------------|
| Memory | Simpler API, Redis built-in | Checkpointing, PostgreSQL persistence, state snapshots |
| MCP | FastMCP native | Massive tool/integration ecosystem |
| Observability | Native OTel (open standard) | LangSmith is more polished (but proprietary) |
| A2A | Real HTTP-based A2A | Graph-based multi-agent orchestration |
| Models | LiteLLM (same) | More native integrations |
| Streaming | Comparable | Deep Agents with auto-compression |
| **Unique gaps** | — | Graph-based state machines, durable execution, massive ecosystem, commercial platform |

---

### 3. CrewAI

**Overall assessment:** Best-in-class memory system. Role-based agent collaboration within "Crews." Enterprise platform with triggers. Memory is the standout feature KAOS should study.

#### Memory & State
Sophisticated unified `Memory` class with:
- **Hierarchical scopes** — filesystem-like paths for organizing memories
- **Composite scoring** — semantic similarity + recency + importance weighting
- **LLM-powered analysis on save** — extracts key information, generates tags
- **Consolidation/deduplication** — merges similar memories automatically
- **Memory slices** — filtered views of memory for specific contexts
- Storage backend is LanceDB by default (local vector store). Custom storage backends supported. Multiple embedder providers. Non-blocking saves with drain on shutdown.

This is significantly more sophisticated than any other framework's memory system.

**Confidence:** HIGH (verified via deep-dive on memory docs)

#### MCP Support
Not prominently featured in main documentation. Has integration tools but MCP is not a first-class concept.

**Confidence:** LOW (not verified, absence in docs doesn't mean absence of feature)

#### Observability
Memory events system for debugging. No native OTel. Enterprise platform has observability features but they're proprietary/commercial.

**Confidence:** MEDIUM

#### A2A / Multi-Agent Communication
Multi-agent via Crews (sequential or hierarchical process execution) and Flows (workflow orchestration). Agents collaborate within a crew by delegating tasks, not across HTTP boundaries. No A2A protocol support. Agents are defined by role, goal, and backstory — collaboration is intra-process.

**Confidence:** HIGH (core feature, well-documented)

#### Model Routing
LLM class supports model strings like `"ollama/llama3.2"` — likely LiteLLM under the hood. Supports major providers.

**Confidence:** MEDIUM (inferred from string format)

#### Streaming
Flows support streaming events. Standard crew execution can stream intermediate results.

**Confidence:** MEDIUM

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | CrewAI Advantage |
|-----------|---------------|-----------------|
| Memory | Redis for distributed, simpler API | Hierarchical scopes, semantic scoring, LLM analysis, consolidation, slices |
| MCP | FastMCP native integration | — |
| Observability | Native OTel | — |
| A2A | Real HTTP-based A2A | Role-based collaboration patterns, task delegation |
| Models | Comparable (both likely LiteLLM) | — |
| Streaming | Comparable | — |
| **Unique gaps** | — | Sophisticated memory with scopes/scoring/consolidation, Flows for orchestration, enterprise platform with triggers (Gmail, Slack, Salesforce) |

---

### 4. Google ADK (Agent Development Kit)

**Overall assessment:** Google's official framework. Strong A2A (they created the protocol) and MCP support. Memory is GCP-locked for anything useful. Multi-language. Previously evaluated and rejected by KAOS for GCP lock-in.

#### Memory & State
`BaseMemoryService` interface with two implementations:
1. **InMemoryMemoryService** — keyword matching, no persistence, no semantic search. Essentially useless for production.
2. **VertexAiMemoryBankService** — GCP Vertex AI locked. Semantic search, persistence, cross-session. The only production-grade option requires GCP.

Session/State objects handle short-term state. Memory is for long-term cross-session knowledge. Custom `MemoryService` can be implemented but no open-source persistent implementation exists.

**Confidence:** HIGH (verified via deep-dive on memory and A2A docs)

#### MCP Support
Full MCP support via `McpToolset`. Supports Stdio and SSE/Streamable HTTP transports. Can use ADK as MCP client and expose ADK tools as MCP servers. Sidecar MCP pattern documented for GKE deployment.

**Confidence:** HIGH (verified via MCP tools docs)

#### Observability
Basic logging. No native OTel. GCP Cloud Monitoring/Logging for deployed agents on GKE/Cloud Run. Essentially: observability = use GCP.

**Confidence:** MEDIUM

#### A2A / Multi-Agent Communication
First-class A2A protocol support — Google created the protocol. `A2AServer` for exposing agents, `RemoteA2aAgent` for consuming remote agents. Available in Python, Go, TypeScript, and Java. Most complete A2A implementation in the ecosystem.

**Confidence:** HIGH (verified via A2A docs)

#### Model Routing
Optimized for Gemini but supports Anthropic Claude, Ollama, vLLM, LiteLLM. Genuinely model-agnostic despite Google branding.

**Confidence:** HIGH (verified via docs)

#### Streaming
Bidirectional streaming (live) with audio/video support. SSE for standard text streaming. Most advanced streaming capabilities of any framework.

**Confidence:** HIGH

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | Google ADK Advantage |
|-----------|---------------|---------------------|
| Memory | RedisMemory works anywhere, no cloud lock-in | Cross-session semantic memory (but GCP-locked) |
| MCP | Comparable | Sidecar MCP pattern for GKE |
| Observability | Native OTel (open standard, any backend) | — |
| A2A | Simpler, OpenAI-compatible | Full A2A protocol (they wrote it), multi-language |
| Models | Comparable (both support LiteLLM) | Native Gemini optimization |
| Streaming | SSE | Bidi-streaming with audio/video |
| **Unique gaps** | — | Multi-language (Python, TS, Go, Java), workflow agents (Sequential, Parallel, Loop), context caching/compression, visual builder |
| **Why KAOS rejected** | No GCP lock-in, simpler A2A, open observability | — |

---

### 5. Microsoft AutoGen

**Overall assessment:** Research-grade multi-agent framework. Event-driven core with gRPC distributed runtime. Strong distributed agent communication but complex. AutoGen Studio provides no-code UI.

#### Memory & State
AgentChat layer maintains conversation history. Core layer uses event-driven state management with message passing. State can persist via the runtime layer. Less emphasis on memory abstractions, more on event/message architecture.

**Confidence:** LOW (docs restructured, couldn't deep-dive)

#### MCP Support
`McpWorkbench` extension for MCP server integration. Wraps MCP servers as tool sources for AutoGen agents.

**Confidence:** MEDIUM

#### Observability
Not prominently featured in documentation. Likely relies on external tooling. No native OTel mentioned.

**Confidence:** LOW (couldn't verify)

#### A2A / Multi-Agent Communication
This is AutoGen's core strength. Two layers:
1. **Core** — event-driven, message-passing architecture. `GrpcWorkerAgentRuntime` enables distributed agents across processes and machines via gRPC.
2. **AgentChat** — higher-level conversational multi-agent patterns (RoundRobin, Selector, Swarm, etc.)

Agents can run on different machines and communicate via gRPC. This is true distributed multi-agent, not just HTTP delegation.

**Confidence:** MEDIUM (based on docs overview)

#### Model Routing
`OpenAIChatCompletionClient` is the primary model interface. Extensions for other providers. Less provider diversity than LiteLLM-based frameworks.

**Confidence:** MEDIUM

#### Streaming
Supported in AgentChat layer. Streaming of intermediate agent messages in multi-agent conversations.

**Confidence:** MEDIUM

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | AutoGen Advantage |
|-----------|---------------|------------------|
| Memory | RedisMemory, clear abstraction | Event-driven state (different paradigm) |
| MCP | FastMCP native | — |
| Observability | Native OTel | — |
| A2A | Simpler HTTP-based | gRPC distributed runtime, true multi-machine agent communication |
| Models | LiteLLM (broader) | — |
| Streaming | Comparable | Multi-agent conversation streaming |
| **Unique gaps** | — | Event-driven architecture, gRPC runtime, AutoGen Studio (no-code UI), Docker code execution, community extensions |

---

### 6. Microsoft Semantic Kernel

**Overall assessment:** Enterprise-grade, .NET-first (also Python, Java). Outstanding OTel support. Process Framework for durable workflows. Strong Azure integration. Different audience than KAOS (enterprise C#/.NET shops).

#### Memory & State
Vector Store Connectors for long-term semantic memory. Supports various vector databases (Azure AI Search, Cosmos DB, Pinecone, Qdrant, etc.). Chat history for conversation state. Separation of conversation memory (short-term) and semantic memory (long-term vector search).

**Confidence:** MEDIUM

#### MCP Support
Plugin system maps naturally to MCP tools. Semantic Kernel's plugin/function model is conceptually similar to MCP's tool model.

**Confidence:** MEDIUM (conceptual mapping, not verified as native MCP)

#### Observability
Excellent OpenTelemetry support — arguably the best after Pydantic AI. Follows GenAI semantic conventions. Provides:
- Logs, metrics, and distributed tracing via Activities/Spans
- Function duration metrics, token usage histograms
- Compatible with Azure Application Insights AND any OTel backend
- Streaming duration metrics

This is a genuine strength and closely matches KAOS's approach.

**Confidence:** HIGH (verified via observability docs)

#### A2A / Multi-Agent Communication
Agent Framework with orchestration patterns: AgentGroupChat, agent collaboration strategies. Process Framework for workflow orchestration (sequential, parallel, state machine). No native A2A protocol — agents collaborate in-process.

**Confidence:** MEDIUM (verified via agent framework docs)

#### Model Routing
Multi-language (C#, Python, Java). Supports OpenAI, Azure OpenAI, and other providers via connectors. Less provider diversity than LiteLLM.

**Confidence:** MEDIUM

#### Streaming
Supported with streaming duration metrics tracked via OTel. First-class streaming in the kernel.

**Confidence:** HIGH

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | Semantic Kernel Advantage |
|-----------|---------------|--------------------------|
| Memory | Redis built-in, simpler | Vector store connectors, semantic memory |
| MCP | FastMCP native | — |
| Observability | Comparable — both excellent OTel | Streaming duration metrics, GenAI semantic conventions, token histograms |
| A2A | Real HTTP-based A2A | Process Framework for durable workflows |
| Models | LiteLLM (broader) | Azure OpenAI optimization |
| Streaming | Comparable | Streaming metrics |
| **Unique gaps** | — | Multi-language (C#, Python, Java), Process Framework, Filters for security/guardrails, enterprise Azure integration |

---

### 7. LlamaIndex

**Overall assessment:** RAG-first framework that added agent capabilities. Unmatched for retrieval/indexing. Agent layer is less mature than pure agent frameworks. Massive integration ecosystem.

#### Memory & State
Agent memory module with chat stores supporting various backends (Redis, DynamoDB, etc.). Session-based conversation memory. Document stores and index stores for RAG knowledge. The memory story is really about document indexing and retrieval, not agent state.

**Confidence:** MEDIUM

#### MCP Support
Explicit MCP support — can use MCP tools with LlamaIndex agents, convert existing tools/workflows to MCP servers, and use LlamaCloud MCP servers. Bidirectional MCP story.

**Confidence:** MEDIUM (confirmed in docs, not deep-dived)

#### Observability
Instrumentation module with callbacks and tracing. Integrates with multiple observability platforms (Arize Phoenix, Langfuse, etc.). Not native OTel but has adapters.

**Confidence:** MEDIUM

#### A2A / Multi-Agent Communication
Multi-agent patterns via LlamaAgents (formerly llama-deploy). Deploys agent workflows as microservices. Workflow-based orchestration. Not A2A protocol — custom service mesh approach.

**Confidence:** MEDIUM

#### Model Routing
Extremely broad LLM and embedding model support — dozens of providers. Has LiteLLM integration. Unique strength in embedding model diversity for RAG.

**Confidence:** HIGH (well-known)

#### Streaming
Streaming events in workflows. Query engine streaming for RAG responses.

**Confidence:** MEDIUM

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | LlamaIndex Advantage |
|-----------|---------------|---------------------|
| Memory | Simpler, purpose-built | Chat stores with Redis, document/index stores |
| MCP | Comparable | LlamaCloud MCP servers |
| Observability | Native OTel | Multi-platform integrations |
| A2A | Real HTTP-based A2A | LlamaAgents microservice deployment |
| Models | Comparable (both LiteLLM) | Embedding model diversity |
| Streaming | Comparable | — |
| **Unique gaps** | — | RAG-first (indexing, retrieval, query engines), LlamaCloud managed service, LlamaParse for documents, property graph index, massive integration ecosystem |

---

### 8. Haystack (deepset)

**Overall assessment:** Pipeline-as-explicit-graph philosophy. Strong RAG/retrieval focus like LlamaIndex but with explicit, debuggable pipelines. Enterprise platform (deepset Cloud). Clean architecture but smaller ecosystem.

#### Memory & State
Pipeline-based — memory is a component you add to pipelines explicitly. `ChatMessageStore` for conversation memory. Everything is a pipeline component: generators, retrievers, converters, memory stores. No magic, no implicit state.

**Confidence:** MEDIUM

#### MCP Support
Can serve pipelines as MCP servers via Hayhooks (the pipeline serving layer). Pipelines become MCP-accessible tools. Less about consuming MCP tools, more about exposing Haystack as MCP.

**Confidence:** MEDIUM

#### Observability
Built-in tracing, logging, and evaluation tools. Pipeline execution is inherently traceable because every step is explicit. Integration with observability platforms.

**Confidence:** MEDIUM

#### A2A / Multi-Agent Communication
No native A2A. Pipelines can be served as REST APIs via Hayhooks. No multi-agent orchestration — Haystack is pipeline-focused, not agent-focused.

**Confidence:** MEDIUM

#### Model Routing
Model-agnostic via integrations. Supports many providers through generator components.

**Confidence:** MEDIUM

#### Streaming
Supported in pipeline generators. Streaming is a property of the generator component in the pipeline.

**Confidence:** MEDIUM

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | Haystack Advantage |
|-----------|---------------|-------------------|
| Memory | Redis distributed, agent-native | Pipeline-explicit memory (debuggable) |
| MCP | FastMCP client | Pipeline-as-MCP-server via Hayhooks |
| Observability | Native OTel | Pipeline tracing is inherently explicit |
| A2A | Real A2A support | — |
| Models | LiteLLM (broader) | — |
| Streaming | Comparable | — |
| **Unique gaps** | — | Pipeline-as-explicit-graph, context engineering, strong RAG/retrieval, deepset enterprise platform |

---

### 9. DSPy

**Overall assessment:** Fundamentally different paradigm. Not an agent orchestration framework — it's a prompt optimization framework. Focuses on automatically finding the best prompts and few-shot examples via optimizers. Apples-to-oranges comparison, but addresses a dimension no other framework does.

#### Memory & State
Conversation history management exists but is basic. No distributed memory concept. State is module parameters (optimized prompts, few-shot examples) not conversation history.

**Confidence:** MEDIUM

#### MCP Support
MCP support documented in tutorials. Can use MCP tools within DSPy modules.

**Confidence:** MEDIUM (confirmed in docs, not deep-dived)

#### Observability
`inspect_history` utility for debugging prompts. Integrates with LiteLLM logging. Debugging & observability tutorial exists. Focus is on understanding what prompts were generated and why, not distributed tracing.

**Confidence:** MEDIUM

#### A2A / Multi-Agent Communication
No multi-agent communication. Single-agent/single-pipeline optimization focus. DSPy modules compose but don't distribute across processes.

**Confidence:** HIGH (this is a fundamental design choice)

#### Model Routing
Uses LiteLLM under the hood for all provider access. Supports OpenAI, Anthropic, Gemini, Databricks, Ollama, and any LiteLLM-supported provider. Same foundation as KAOS.

**Confidence:** HIGH (verified in docs)

#### Streaming
`StreamListener` and `streamify` utilities documented. Streaming is available but not the focus.

**Confidence:** MEDIUM

#### Gap Analysis vs KAOS
| Dimension | KAOS Advantage | DSPy Advantage |
|-----------|---------------|---------------|
| Memory | RedisMemory, memory abstraction | — |
| MCP | FastMCP native | — |
| Observability | Native OTel | Prompt inspection/debugging |
| A2A | Real A2A support | — |
| Models | Comparable (both LiteLLM) | — |
| Streaming | Comparable | — |
| **Unique gaps** | — | Prompt optimization (GEPA, MIPROv2, BootstrapFewShot), declarative signatures, automatic prompt compilation, fine-tuning integration. Entirely different value proposition. |

---

## Feature Comparison Matrix

Ratings: **✓** = Full support | **◐** = Partial/limited | **✗** = Not supported | **$** = Requires paid/cloud service

| Dimension | KAOS | Pydantic AI | LangChain/LangGraph | CrewAI | Google ADK | AutoGen | Semantic Kernel | LlamaIndex | Haystack | DSPy |
|-----------|------|-------------|---------------------|--------|------------|---------|----------------|------------|----------|------|
| **Distributed Memory** | ✓ (Redis) | ✗ | ◐ (PostgreSQL) | ◐ (LanceDB local) | ◐/$ (Vertex only) | ◐ | ◐ (Vector stores) | ◐ (Redis chat store) | ◐ | ✗ |
| **Session-scoped Memory** | ✓ | ◐ (manual) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ |
| **Semantic/Long-term Memory** | ✗ | ✗ | ◐ | ✓ (scoring + consolidation) | $ (Vertex) | ✗ | ✓ (vector stores) | ✓ (indexes) | ◐ | ✗ |
| **MCP Client** | ✓ | ✓ | ✓ | ◐ | ✓ | ✓ | ◐ | ✓ | ◐ | ◐ |
| **MCP Server** | ✗ | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ (Hayhooks) | ✗ |
| **OTel Observability** | ✓ | ✓ | ✗ (LangSmith) | ✗ | ✗ | ✗ | ✓ | ◐ (adapters) | ◐ | ✗ |
| **A2A Protocol** | ◐ (custom) | ✓ (FastA2A) | ✗ | ✗ | ✓ (native) | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Multi-Agent Orchestration** | ◐ (delegation) | ✓ (graph) | ✓ (graph) | ✓ (crews) | ✓ (workflow agents) | ✓ (core strength) | ✓ (agent framework) | ✓ (LlamaAgents) | ✗ | ✗ |
| **LiteLLM / Provider-Agnostic** | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ | ◐ | ✓ | ✓ | ✓ |
| **Model Fallback/Failover** | ✗ | ✓ (FallbackModel) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **SSE/Text Streaming** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Structured Output Streaming** | ✗ | ✓ | ◐ | ✗ | ◐ | ✗ | ◐ | ✗ | ✗ | ✗ |
| **Bidi/Audio/Video Streaming** | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **OpenAI-Compatible API** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Durable Execution** | ✗ | ✓ | ✓ (LangGraph) | ◐ (Flows) | ◐ | ✗ | ✓ (Process Framework) | ✗ | ✗ | ✗ |
| **Type-Safe Outputs** | ✗ | ✓ (Pydantic) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (signatures) |
| **Prompt Optimization** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| **No-Code UI** | ✗ | ✗ | ✗ | $ (Enterprise) | ✓ (visual builder) | ✓ (Studio) | ✗ | ✗ | ✗ | ✗ |
| **Multi-Language SDK** | ✗ (Python) | ✗ (Python) | ✓ (Py, JS) | ✗ (Python) | ✓ (Py, TS, Go, Java) | ✓ (Py, .NET) | ✓ (C#, Py, Java) | ✓ (Py, TS) | ✗ (Python) | ✗ (Python) |

---

## Table Stakes vs Differentiators

### Table Stakes

Features users **expect** in any agentic AI framework in 2026. Missing = product feels incomplete.

| Feature | Why Expected | KAOS Status | Complexity to Add |
|---------|--------------|-------------|-------------------|
| Session-scoped memory | Every chatbot needs conversation history | ✓ Has it | — |
| LLM provider agnosticism | No one wants vendor lock-in | ✓ Has it (LiteLLM) | — |
| Tool/function calling | Core agentic capability | ✓ Has it | — |
| SSE streaming | Users expect real-time responses | ✓ Has it | — |
| MCP client support | MCP is becoming the standard for tool integration | ✓ Has it (FastMCP) | — |
| Basic observability (tracing) | Debugging agents is non-negotiable | ✓ Has it (OTel) | — |
| Multi-agent orchestration | At least basic agent delegation | ◐ Has delegation | Medium (add graph/workflow patterns) |
| Structured output validation | Type-safe responses are expected | ✗ Missing | Medium |
| Model fallback/failover | Production reliability requires it | ✗ Missing | Low (LiteLLM supports this) |

### Differentiators

Features that set each framework apart. Not expected everywhere, but create competitive advantage.

| Framework | Key Differentiator | What Makes It Special |
|-----------|-------------------|----------------------|
| **KAOS** | OpenAI-compatible API + container-native | Deploy any agent as a standard API endpoint, build custom images. No framework lock-in for consumers. |
| **Pydantic AI** | Type-safe dependency injection + structured outputs | Pydantic validation on agent outputs. Compile-time-like safety for agent behavior. |
| **LangChain/LangGraph** | Graph-based durable execution | Stateful state machines with checkpointing. Resume workflows after failures. |
| **CrewAI** | Sophisticated semantic memory | Hierarchical scopes, composite scoring, LLM-powered analysis, auto-consolidation. No one else has this. |
| **Google ADK** | Multi-language + bidi streaming | Python, TS, Go, Java SDKs. Live audio/video streaming. Massive language reach. |
| **AutoGen** | gRPC distributed agent runtime | True distributed multi-agent across machines via gRPC. Research-grade multi-agent patterns. |
| **Semantic Kernel** | Enterprise .NET + Process Framework | C#/Java enterprise shops. Durable workflow processes. Azure-native. |
| **LlamaIndex** | RAG-first with massive index types | Property graphs, vector indexes, document parsing. Unmatched retrieval sophistication. |
| **Haystack** | Pipeline-as-explicit-graph | Every step visible and debuggable. No hidden magic. Clean composition. |
| **DSPy** | Automatic prompt optimization | Optimizers find best prompts automatically. Fundamentally different value — no one else does this. |

### Anti-Features

Features to **explicitly NOT build** in KAOS. Either they violate KAOS's philosophy or the cost outweighs the benefit.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Proprietary observability platform | Violates open-standards philosophy. LangSmith/Logfire are vendor lock-in. | Stay with OTel. Let users bring their own backend (Jaeger, Grafana, Datadog, etc.) |
| Cloud-locked memory (Vertex, Azure) | KAOS runs anywhere — GCP/Azure lock-in is a non-starter | Keep Redis/open backends. Add PostgreSQL if needed. |
| No-code visual builder | Massive engineering effort, low alignment with developer-tool positioning | Focus on great SDK and API DX. Let third parties build UIs on top of the OpenAI-compatible API. |
| Graph-based state machines (LangGraph-style) | Adds enormous complexity. KAOS's simple tool loop is a feature, not a bug. | Add lightweight workflow patterns (sequential, parallel) without a full graph engine. |
| Prompt optimization (DSPy-style) | Orthogonal to KAOS's purpose. DSPy is a complementary tool, not a competitor. | Document how to use DSPy modules alongside KAOS agents. |
| Role/persona-based agent definition (CrewAI-style) | Over-abstraction. Agents should be defined by their tools and instructions, not "role + goal + backstory." | Keep the current model: system prompt + tools + memory = agent. |
| Multi-language SDKs | Engineering cost is 4x+. Python is the dominant AI/ML language. | Stay Python-only. The OpenAI-compatible API means any language can consume KAOS agents without a SDK. |

---

## Feature Dependencies

```
Structured Output Validation → Streaming Structured Outputs (need validation before you can stream validated outputs)
MCP Client (✓ done) → MCP Server (expose KAOS agents as MCP servers)
Session Memory (✓ done) → Semantic/Long-term Memory (need session memory before cross-session knowledge)
A2A Delegation (✓ done) → A2A Protocol Compliance (standardize existing A2A on the protocol spec)
Model Routing (✓ done) → Model Fallback/Failover (add retry/fallback on top of LiteLLM)
OTel Tracing (✓ done) → GenAI Semantic Conventions (adopt standard attribute names for AI operations)
```

## MVP Recommendation (Next Priorities)

**Prioritize** (high value, reasonable complexity):
1. **Model Fallback/Failover** — Low complexity, high production value. LiteLLM already supports this; surface it in KAOS config.
2. **Structured Output Validation** — Medium complexity, table stakes in 2026. Pydantic AI and DSPy both demonstrate this is expected.
3. **A2A Protocol Compliance** — KAOS already has A2A delegation. Standardizing on the A2A protocol (Google's spec) is incremental and opens interop with Pydantic AI and Google ADK agents.
4. **MCP Server Support** — Expose KAOS agents as MCP servers. Enables discovery by IDEs, other frameworks, and MCP-aware tools.

**Defer** (high effort or low alignment):
- **Semantic/Long-term Memory**: Valuable but complex. CrewAI's approach is best-in-class but took significant engineering. Wait for clear user demand.
- **Durable Execution**: Useful for long-running workflows but adds significant complexity. Not table stakes yet.
- **Bidi/Audio/Video Streaming**: Niche use case. Google ADK is the only framework with this.

---

## Sources

| Framework | Source | Confidence |
|-----------|--------|------------|
| Pydantic AI | Official docs (ai.pydantic.dev) — MCP, A2A, Models, Logfire pages | HIGH |
| LangChain/LangGraph | Official docs (python.langchain.com, langchain-ai.github.io/langgraph) | MEDIUM |
| CrewAI | Official docs (docs.crewai.com) — Memory deep-dive | HIGH |
| Google ADK | Official docs (google.github.io/adk-docs) — Memory, A2A, MCP pages | HIGH |
| AutoGen | Official docs (microsoft.github.io/autogen) | MEDIUM |
| Semantic Kernel | Official docs (learn.microsoft.com) — Observability, Agent Framework | HIGH |
| LlamaIndex | Official docs (docs.llamaindex.ai) | MEDIUM |
| Haystack | Official docs (docs.haystack.deepset.ai) | MEDIUM |
| DSPy | Official docs (dspy.ai) | MEDIUM |
