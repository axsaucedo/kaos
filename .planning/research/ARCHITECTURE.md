# Architecture Patterns: Framework Integration Analysis

**Domain:** Kubernetes-native agent orchestration platform (KAOS) — framework compatibility
**Researched:** 2026-02-20
**Overall confidence:** MEDIUM-HIGH (Pydantic AI, Google ADK, AutoGen: HIGH; others: MEDIUM)

## KAOS Architecture Constraints

Before evaluating frameworks, the key architectural constraints that any integrated framework must satisfy:

### The Container Contract

Every agent in KAOS runs as a **containerized pod managed by a Kubernetes operator**. The operator:

1. **Owns the Deployment lifecycle** — creates, updates, deletes Deployments via `AgentReconciler`
2. **Injects ALL configuration via environment variables** — `AGENT_NAME`, `MODEL_API_URL`, `MODEL_NAME`, `MCP_SERVERS`, `MCP_SERVER_<name>_URL`, `PEER_AGENTS`, `PEER_AGENT_<NAME>_CARD_URL`, `MEMORY_*`, `OTEL_*`, `AGENTIC_LOOP_MAX_STEPS`, `TOOL_CALL_MODE`, etc.
3. **Manages health probes** — expects `/health` (liveness) and `/ready` (readiness) on port 8000
4. **Resolves cross-cutting concerns** — ModelAPI endpoints, MCP Server endpoints, peer agent discovery, telemetry config, memory backend config
5. **Supports podSpec strategic merge patches** — users can override container image, command, args, resources, additional env vars

### The Data-Plane Contract

The current KAOS data-plane (`kaos-framework`) provides:

| Capability | Implementation | Interface |
|---|---|---|
| **HTTP Server** | FastAPI on port 8000 | `/health`, `/ready`, `/.well-known/agent`, `/v1/chat/completions`, `/memory/*` |
| **Agent Loop** | Two-phase: action collection → final response | `Agent.process_message()` async iterator |
| **Model Client** | OpenAI-compatible via httpx | `ModelAPI` class, reads `MODEL_API_URL` |
| **MCP Client** | Official MCP SDK, Streamable HTTP transport | `MCPClient` class, connection-per-request |
| **A2A Protocol** | `/.well-known/agent` discovery, `/v1/chat/completions` delegation | `RemoteAgent` class, `task-delegation` role |
| **Memory** | `LocalMemory` (in-process), `RedisMemory` (distributed), `NullMemory` (no-op) | Session/event-based API |
| **Telemetry** | `KaosOtelManager` singleton, W3C trace propagation, OTLP gRPC export | Inline span management, custom metrics |

### Integration Model

Any framework integration must follow one of these patterns:

- **Pattern A: Replace kaos-framework** — Framework provides its own server, agent loop, and tool calling. KAOS operator injects config; framework reads env vars and exposes required HTTP endpoints.
- **Pattern B: Wrap kaos-framework** — Framework's agent/tools run inside the existing kaos-framework server. Framework provides the reasoning engine; KAOS provides HTTP, A2A, memory, telemetry.
- **Pattern C: Adapter layer** — Thin adapter translates between framework constructs and KAOS data-plane contracts. Framework runs natively; adapter bridges the gap.

---

## Per-Framework Architecture Analysis

### 1. Pydantic AI

**Confidence:** HIGH (verified via official docs: main page, A2A page, MCP page)

#### Container Compatibility
**Score: 9/10**

Pydantic AI is fundamentally a **library, not a platform**. Agents are Python objects (`Agent(model, system_prompt, tools)`) with no deployment assumptions. This is ideal for KAOS — the framework runs inside any container image with zero opinions about how it gets there.

- No background services or daemons required
- No special filesystem requirements
- Agents are instantiated in Python code, configured however you want
- Uses `pydantic-settings` for config (same as KAOS's `AgentServerSettings`)

#### Operator Integration
**Score: 9/10**

Near-perfect fit. Pydantic AI agents accept all config at construction time:
- Model selection: `Agent(model='openai:gpt-4o')` — can read from `MODEL_NAME` env var
- System prompt: string or callable — can read from `AGENT_INSTRUCTIONS`
- Tools: decorated Python functions — can be dynamically registered
- No global state or singleton patterns that conflict with operator lifecycle

**Key compatibility point:** Pydantic AI uses the same `pydantic-settings` BaseSettings pattern as KAOS's `AgentServerSettings`, making env-var-based configuration trivial.

#### Memory Architecture
**Score: 6/10**

Pydantic AI has **message-based conversation history** but no built-in session/memory persistence abstraction. You pass `message_history` to `agent.run()`. This means:
- KAOS's `LocalMemory`/`RedisMemory` would need an adapter to convert MemoryEvents to Pydantic AI message format
- Alternatively, KAOS memory stays as-is and Pydantic AI runs with explicit message passing (Pattern B)
- No conflict — just requires bridging work

#### Observability Integration
**Score: 8/10**

Pydantic AI has native OpenTelemetry support via **Logfire** (which is OTel-compatible):
- Built-in span creation for agent runs, model calls, tool executions
- W3C trace context propagation
- Compatible with any OTel collector (not locked to Logfire)
- Could coexist with or replace `KaosOtelManager`

#### A2A Architecture
**Score: 10/10**

**Best-in-class A2A support.** Pydantic AI has native A2A via `FastA2A`:
- `agent.to_a2a()` creates a Starlette ASGI app with full A2A server
- `A2AClient` for consuming A2A services
- Implements the A2A protocol specification natively
- Discovery via `/.well-known/agent.json` (close to KAOS's `/.well-known/agent`)

The slight endpoint difference (`agent.json` vs bare path) is trivial to bridge.

#### MCP Integration
**Score: 9/10**

Native MCP client support:
- `mcp_server = MCPServerHTTP(url=...)` — drop-in for KAOS's MCP_SERVER env var pattern
- Tool discovery happens automatically
- Uses the official MCP protocol
- Can pass MCP servers to agent constructor: `Agent(mcp_servers=[...])`

#### Migration Path
**Score: 9/10**

Easiest migration of all frameworks:
1. Replace `Agent` class with `pydantic_ai.Agent`
2. Replace `ModelAPI` with Pydantic AI's model abstraction (supports OpenAI-compatible endpoints)
3. Wrap MCP servers using `MCPServerHTTP`
4. Wrap in existing FastAPI server OR use `agent.to_a2a()` for A2A endpoints
5. Memory bridging is the only non-trivial work

**Architecture Fit Score: 9/10**

---

### 2. LangChain / LangGraph

**Confidence:** MEDIUM-HIGH (verified via official docs overview, training data for architecture details)

#### Container Compatibility
**Score: 8/10**

LangChain/LangGraph are Python libraries with no deployment assumptions. LangGraph adds stateful graph execution but still runs as in-process Python. No daemons or background services.

- LangGraph's `StateGraph` is a Python object — instantiate in container
- LangServe can expose as HTTP API, but not required
- LangSmith integration is optional (cloud-based tracing)

Minor concern: LangGraph's checkpointing wants a persistence backend (SQLite, Postgres) which adds container complexity.

#### Operator Integration
**Score: 7/10**

Good but not seamless:
- Model config: `ChatOpenAI(base_url=..., model=...)` reads well from env vars
- Tool registration: programmatic, works fine
- LangGraph needs a `checkpointer` for stateful workflows — KAOS operator would need to provision this (e.g., Redis or Postgres sidecar)
- LangSmith API key injection via env vars is straightforward

#### Memory Architecture
**Score: 7/10**

LangGraph has sophisticated memory via **checkpointers**:
- `MemorySaver` (in-memory), `SqliteSaver`, `PostgresSaver`
- Thread-based conversation management
- State is the graph's accumulated state, not a simple event log

Mismatch with KAOS: LangGraph's memory is graph-state-based (accumulated state dict), not event-based (MemoryEvent list). Integration requires choosing one system or bridging both.

#### Observability Integration
**Score: 6/10**

LangChain's observability is primarily through **LangSmith** (proprietary cloud service):
- Rich tracing of chains, LLM calls, tool calls
- LangSmith has some OTel export capability but it's not native OTel
- Community has `opentelemetry-instrumentation-langchain` packages but they're third-party
- Would need to layer OTel instrumentation or accept LangSmith as the observability backend

This is a moderate concern — KAOS's OTel-native approach doesn't align naturally.

#### A2A Architecture
**Score: 4/10**

LangChain/LangGraph has **no native A2A protocol support**:
- LangServe exposes chains as REST APIs but with its own format
- No `/.well-known/agent` endpoint
- No agent card concept
- Multi-agent is within a single LangGraph, not across network boundaries
- Would need to build A2A adapter layer entirely

#### MCP Integration
**Score: 7/10**

LangChain has MCP tool integration:
- `langchain-mcp-adapters` package
- Converts MCP tools to LangChain tools
- Works with Streamable HTTP transport
- Not as seamless as Pydantic AI's native MCP support

#### Migration Path
**Score: 6/10**

Moderate migration complexity:
1. Replace `Agent` agentic loop with LangGraph `StateGraph`
2. Replace `ModelAPI` with LangChain's `ChatOpenAI`
3. Build A2A adapter layer (significant work)
4. Choose between KAOS memory and LangGraph checkpointers
5. Decide on LangSmith vs KAOS OTel for observability
6. More moving parts = more integration surface

**Architecture Fit Score: 6/10**

---

### 3. CrewAI

**Confidence:** MEDIUM (verified via official docs intro, training data for internals)

#### Container Compatibility
**Score: 7/10**

CrewAI runs as Python code — agents and crews are in-process objects. However:
- CrewAI has a more opinionated runtime (`crewai run` CLI)
- Flows and Crews assume a specific execution model
- Enterprise features are cloud-hosted (CrewAI Enterprise)
- Heavier dependency tree than Pydantic AI

#### Operator Integration
**Score: 6/10**

Moderate fit:
- Agent creation: `Agent(role=..., goal=..., backstory=..., llm=...)` — config from env vars works
- Crew orchestration: `Crew(agents=[...], tasks=[...], process=Process.sequential)` — more opinionated than KAOS's model
- CrewAI wants to own the multi-agent orchestration pattern — conflicts with KAOS operator's role as orchestrator
- The "Crew" abstraction assumes agents are co-located, not networked

#### Memory Architecture
**Score: 7/10**

CrewAI has built-in memory:
- Short-term memory (conversation context)
- Long-term memory (persistent across sessions)
- Entity memory (structured entity tracking)
- Supports custom memory providers

Better memory story than Pydantic AI, but the memory model is tightly coupled to Crew execution patterns.

#### Observability Integration
**Score: 5/10**

CrewAI's observability is primarily through:
- Built-in logging with verbose mode
- CrewAI Enterprise telemetry (proprietary)
- No native OTel support
- Would need custom instrumentation to bridge to KAOS's OTel stack

#### A2A Architecture
**Score: 3/10**

**Poor A2A fit.** CrewAI's multi-agent model is:
- Intra-process: agents communicate within a single Crew
- No network protocol for agent-to-agent communication
- No discovery mechanism
- The "crew" is the unit of deployment, not individual agents
- Fundamental mismatch with KAOS's "each agent is a pod" model

#### MCP Integration
**Score: 6/10**

CrewAI supports MCP tools:
- `MCPServerAdapter` for connecting to MCP servers
- Tool discovery works
- Less mature than Pydantic AI or LangChain MCP integration

#### Migration Path
**Score: 5/10**

Significant migration challenges:
1. CrewAI's multi-agent model (Crew) conflicts with KAOS's distributed agent model
2. Either run entire Crew in one pod (defeats KAOS's purpose) or break apart Crew abstractions
3. A2A layer must be built from scratch
4. OTel instrumentation must be built from scratch
5. Memory model mapping is complex

**Architecture Fit Score: 5/10**

---

### 4. Google ADK (Agent Development Kit)

**Confidence:** HIGH (verified via official docs: quickstart, A2A intro, deployment guides)

#### Container Compatibility
**Score: 9/10**

Google ADK is designed for containerized deployment:
- `adk api_server` creates a FastAPI server — similar to KAOS's approach
- Agents are Python objects with explicit config
- Official GKE deployment documentation exists
- Supports Ollama, vLLM, LiteLLM for local/custom model serving
- No proprietary platform lock-in for core features

#### Operator Integration
**Score: 8/10**

Strong fit:
- Agent creation: `Agent(name=..., model=..., instruction=..., tools=[...])` — clean env var mapping
- Model config: supports OpenAI-compatible endpoints via LiteLLM
- `adk api_server` exposes health endpoints suitable for K8s probes
- Environment variable configuration is well-supported
- Sub-agent configuration is declarative

#### Memory Architecture
**Score: 9/10**

**Best-in-class memory abstraction:**
- `InMemorySessionService` (like KAOS's `LocalMemory`)
- `DatabaseSessionService` (SQL-backed)
- `VertexAiSessionService` (cloud-managed)
- Session-based model with events — **nearly identical to KAOS's memory model**
- Clean interface for custom implementations

KAOS's `LocalMemory` was explicitly designed "similar to Google ADK's InMemorySessionService" (per code comments). Near-perfect alignment.

#### Observability Integration
**Score: 7/10**

Google ADK has:
- Built-in tracing for agent execution
- Integration with Google Cloud's operations suite
- OTel support via Google Cloud's OTel integration
- Not as natively OTel-first as KAOS's approach, but compatible
- Trace context propagation supported

#### A2A Architecture
**Score: 10/10**

**Best A2A support alongside Pydantic AI:**
- Native A2A protocol implementation: `RemoteA2aAgent` + `A2AServer`
- Built-in agent card generation and discovery
- HTTP-based agent-to-agent communication
- Google co-authored the A2A protocol specification
- Task-based delegation model aligns well with KAOS's delegation pattern

#### MCP Integration
**Score: 9/10**

Native MCP tools support:
- `MCPToolset.from_server(url=...)` for connecting to MCP servers
- Automatic tool discovery and schema mapping
- First-class MCP support in the agent constructor
- Streamable HTTP transport support

#### Migration Path
**Score: 8/10**

Smooth migration path:
1. Replace `Agent` class with `google.adk.agents.Agent`
2. Replace `ModelAPI` with ADK's model abstraction (LiteLLM-backed)
3. ADK's `api_server` provides similar HTTP endpoints
4. Memory model is nearly identical — straightforward bridging
5. A2A works natively — may need minor endpoint path adjustments
6. MCP integration is drop-in

**Architecture Fit Score: 9/10**

---

### 5. Microsoft AutoGen

**Confidence:** MEDIUM-HIGH (verified via official docs main page, training data for architecture)

#### Container Compatibility
**Score: 7/10**

AutoGen has two layers:
- **Core**: event-driven, message-passing agents with `GrpcWorkerAgentRuntime` for distributed deployment
- **AgentChat**: higher-level conversational patterns

The Core layer is designed for distributed systems, which is good. However:
- `GrpcWorkerAgentRuntime` wants a gRPC host process — adds infrastructure
- More complex to containerize than simpler libraries
- Multiple runtime components may need coordination

#### Operator Integration
**Score: 5/10**

Mixed fit:
- AutoGen's distributed runtime has its own service discovery and messaging
- `GrpcWorkerAgentRuntime` expects a gRPC-based communication infrastructure
- This partially duplicates what KAOS operator provides (service discovery, networking)
- Configuration is more programmatic than env-var-based
- Would need significant adaptation to work within KAOS's env-var injection model

#### Memory Architecture
**Score: 6/10**

AutoGen's memory model:
- Chat history managed per conversation
- AgentChat layer has `ChatCompletionContext` for managing conversation state
- No session-based persistence abstraction comparable to KAOS
- Extensions can add memory, but it's not a first-class concern

#### Observability Integration
**Score: 6/10**

AutoGen observability:
- OpenTelemetry support via `autogen-ext[opentelemetry]`
- Trace context for agent interactions
- Not as deeply integrated as KAOS's inline span management
- Would need bridging for custom KAOS metrics

#### A2A Architecture
**Score: 5/10**

AutoGen has its own multi-agent communication:
- Core uses message-passing between agent runtimes
- AgentChat has team patterns (RoundRobin, Selector, etc.)
- No native A2A protocol (HTTP-based discovery/delegation)
- `GrpcWorkerAgentRuntime` uses gRPC, not HTTP REST
- Would need adapter for KAOS's HTTP-based A2A pattern

#### MCP Integration
**Score: 7/10**

AutoGen has MCP support via Extensions:
- `McpWorkbench` for connecting to MCP servers
- Tool discovery and execution
- Works but not as seamless as Pydantic AI or ADK

#### Migration Path
**Score: 4/10**

Challenging migration:
1. AutoGen's distributed runtime partially overlaps/conflicts with KAOS operator
2. gRPC vs HTTP communication mismatch
3. Need to decide: use AutoGen's runtime OR strip it out and use only agent logic
4. If stripping, you lose much of AutoGen's value (distributed execution)
5. If keeping, you have two orchestration systems fighting
6. Complex dependency tree

**Architecture Fit Score: 5/10**

---

### 6. Microsoft Semantic Kernel

**Confidence:** MEDIUM (verified via official docs overview, training data for internals)

#### Container Compatibility
**Score: 8/10**

Semantic Kernel is a lightweight SDK (available in C#, Python, Java):
- Designed as middleware, not a platform
- No daemon processes or background services
- Python version is a pip package with clean dependencies
- Enterprise-ready with security hooks and filters

#### Operator Integration
**Score: 7/10**

Good library-level fit:
- `Kernel` object is the central construct — instantiate with config from env vars
- Plugin model: add functions as "plugins" that LLMs can call
- Model connectors: OpenAI, Azure OpenAI, and others — configurable via env vars
- `KernelFunction` decorators for tool registration
- No global state that conflicts with operator lifecycle

#### Memory Architecture
**Score: 7/10**

Semantic Kernel has sophisticated memory:
- `SemanticTextMemory` for vector-based recall
- `VolatileMemoryStore`, `AzureCognitiveSearchMemoryStore`, etc.
- Chat history management
- Memory is pluggable with clean interfaces

Moderate alignment with KAOS — different abstraction (vector memory vs event log) but adaptable.

#### Observability Integration
**Score: 8/10**

**Strong OTel support:**
- Built-in telemetry hooks
- Semantic conventions for AI operations
- Filters and hooks for custom instrumentation
- Designed for enterprise observability requirements
- Compatible with standard OTel collectors

#### A2A Architecture
**Score: 3/10**

**No A2A protocol support:**
- Semantic Kernel is designed for single-agent scenarios
- Multi-agent support is via the separate AutoGen integration
- No agent discovery mechanism
- No HTTP-based agent-to-agent protocol
- Would need complete A2A adapter layer

#### MCP Integration
**Score: 6/10**

MCP support is emerging:
- `semantic-kernel-mcp` package exists
- Tool import from MCP servers
- Less mature than Pydantic AI or ADK
- Growing support given Microsoft's involvement in MCP spec

#### Migration Path
**Score: 6/10**

Moderate migration:
1. Replace `Agent` loop with Semantic Kernel's planner/agent patterns
2. Plugin model maps well to KAOS's tool concept
3. Model connectors work with OpenAI-compatible endpoints
4. A2A adapter must be built (significant work)
5. Memory bridging needed but feasible
6. OTel alignment is good

**Architecture Fit Score: 6/10**

---

### 7. LlamaIndex

**Confidence:** MEDIUM (verified via official docs landing page/structure, training data for internals)

#### Container Compatibility
**Score: 8/10**

LlamaIndex is a Python library focused on RAG and data indexing:
- Core library is import-and-use, no deployment assumptions
- **LlamaAgents** (new agent workflow layer) provides deployment tools including `llamactl`
- Workflows can be run as servers
- No daemons required for core usage

#### Operator Integration
**Score: 7/10**

Good fit at the library level:
- LLM config: `OpenAI(api_base=..., model=...)` from env vars
- Tool registration: `FunctionTool` from Python functions
- Agent creation: `ReActAgent.from_tools(tools, llm=llm)`
- LlamaAgents workflows have their own deployment model (potential conflict with KAOS operator)

#### Memory Architecture
**Score: 8/10**

LlamaIndex has robust memory/storage:
- `ChatMemoryBuffer` for conversation context
- `ChatStore` abstraction (Redis, Simple, etc.)
- Document stores, index stores, vector stores
- Session management via memory abstractions
- Better storage story than most frameworks

Good alignment with KAOS — `ChatStore` with Redis backend maps well to `RedisMemory`.

#### Observability Integration
**Score: 7/10**

LlamaIndex has an instrumentation framework:
- `Instrumentation` module with span handlers
- Callbacks for LLM calls, retrieval, etc.
- OpenTelemetry integration via community packages
- `LlamaDebugHandler` for development
- Not as natively OTel as KAOS, but adaptable

#### A2A Architecture
**Score: 4/10**

Limited A2A:
- LlamaAgents has multi-agent workflows but within a single deployment
- No native A2A protocol
- No agent discovery endpoint
- Multi-agent patterns are in-process or via LlamaAgents' internal message passing
- Would need adapter for KAOS's HTTP-based A2A

#### MCP Integration
**Score: 8/10**

Good MCP support:
- `McpToolSpec` for connecting to MCP servers
- Tool discovery and automatic conversion to LlamaIndex tools
- Documented in official docs (`module_guides/mcp/`)
- Can also expose LlamaIndex tools AS MCP tools

#### Migration Path
**Score: 6/10**

Moderate migration:
1. Replace agent loop with LlamaIndex `AgentRunner` / Workflows
2. RAG capabilities are a significant value-add beyond KAOS's current scope
3. A2A adapter needed (significant work)
4. Memory model maps reasonably well (ChatStore ↔ KAOS Memory)
5. LlamaIndex is strongest for RAG — if agents mostly do retrieval, this is compelling
6. If agents are primarily tool-calling/delegation, LlamaIndex adds less value

**Architecture Fit Score: 6/10**

---

### 8. Haystack (deepset)

**Confidence:** MEDIUM (verified via official docs intro, training data for architecture)

#### Container Compatibility
**Score: 8/10**

Haystack is a pipeline-oriented framework:
- Python library with clean dependencies
- Pipelines are Python objects — no deployment assumptions
- Components are modular and composable
- v2.x is a clean rewrite with better architecture

#### Operator Integration
**Score: 7/10**

Good library-level fit:
- Components accept config at construction
- `Pipeline.add_component()` is programmatic
- Model config via component parameters
- No global state conflicts

However, Haystack's pipeline model is DAG-based (directed acyclic graph), which doesn't naturally map to KAOS's loop-based agent execution.

#### Memory Architecture
**Score: 5/10**

Haystack is primarily a pipeline framework, not a conversational agent framework:
- `ConversationMemory` component exists but is basic
- `InMemoryDocumentStore` for document storage (RAG-focused)
- Chat history management is an add-on, not core
- Less sophisticated than KAOS's session/event model

#### Observability Integration
**Score: 7/10**

Haystack has good observability:
- Built-in tracing and logging
- Content tracing for debugging
- OpenTelemetry support via integration
- Pipeline execution tracing

#### A2A Architecture
**Score: 2/10**

**No A2A support:**
- Haystack is a pipeline framework, not a multi-agent framework
- No agent discovery or delegation
- Agent component exists but as a pipeline component, not a network entity
- Would need complete A2A implementation from scratch

#### MCP Integration
**Score: 5/10**

Limited MCP support:
- Tools concept exists via the `Tool` component
- No native MCP client integration
- Would need custom component to bridge MCP tools to Haystack tools
- Community may have integrations but not first-party

#### Migration Path
**Score: 4/10**

Challenging migration:
1. Haystack's pipeline model differs significantly from KAOS's agent loop
2. Agent component is not equivalent to KAOS's Agent
3. No A2A — complete build required
4. Memory model is document-focused, not session-focused
5. Best suited for RAG pipeline components, not general agent orchestration
6. Could work as a specialized component inside KAOS agents (e.g., for RAG sub-tasks)

**Architecture Fit Score: 4/10**

---

### 9. DSPy

**Confidence:** MEDIUM (verified via official docs main page, training data for architecture)

#### Container Compatibility
**Score: 8/10**

DSPy is a Python library focused on LM program optimization:
- Pure Python, no deployment requirements
- `dspy.configure(lm=...)` is the only global state
- Modules are serializable (save/load)
- No daemons or background services

#### Operator Integration
**Score: 6/10**

Moderate fit:
- LM configuration: `dspy.LM("openai/model", api_base=..., api_key=...)` from env vars
- Module definition is code-based (Signatures, Modules)
- `dspy.configure()` is global — only one LM config per process (matches KAOS's one-agent-per-pod)
- Tool support via `dspy.Tool` — programmatic registration
- Optimized programs are saved as artifacts — needs a loading/serving pattern

#### Memory Architecture
**Score: 3/10**

DSPy has minimal memory:
- `dspy.History` for conversation tracking
- No session management
- No persistence abstraction
- DSPy is designed for stateless inference with optimized prompts/weights
- Would need to rely entirely on KAOS's memory system

#### Observability Integration
**Score: 5/10**

DSPy observability:
- `inspect_history()` for debugging
- Integration with observability tools via community packages
- MLflow tracking for optimization runs
- Not natively OTel-instrumented
- Would need custom instrumentation

#### A2A Architecture
**Score: 2/10**

**No A2A support:**
- DSPy is a programming framework for single LM programs
- No multi-agent networking concept
- No agent discovery or delegation protocols
- `dspy.ReAct` is a single-agent pattern
- Complete A2A implementation would be needed

#### MCP Integration
**Score: 7/10**

DSPy has MCP support:
- `dspy.Tool` can wrap MCP tools
- MCP tutorial exists in official docs
- Tool calling is a core DSPy concept
- Integration is functional but not as polished as Pydantic AI or ADK

#### Migration Path
**Score: 5/10**

Moderate-to-challenging migration:
1. DSPy's value is in **prompt optimization**, not agent orchestration
2. Best used as an **inner component** — optimize the LM calls within a KAOS agent
3. Not suitable as a full agent framework replacement
4. No A2A, no memory, no serving — these all stay with KAOS
5. Integration pattern: DSPy module runs inside KAOS agent's process_message()
6. Unique value: automatic prompt tuning is a differentiator no other framework offers

**Architecture Fit Score: 5/10** (as full replacement) / **7/10** (as inner optimization layer)

---

## Integration Complexity Matrix

| Framework | Container | Operator | Memory | OTel | A2A | MCP | Migration | **Fit Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Pydantic AI** | 9 | 9 | 6 | 8 | 10 | 9 | 9 | **9** |
| **Google ADK** | 9 | 8 | 9 | 7 | 10 | 9 | 8 | **9** |
| **LangChain/LangGraph** | 8 | 7 | 7 | 6 | 4 | 7 | 6 | **6** |
| **Semantic Kernel** | 8 | 7 | 7 | 8 | 3 | 6 | 6 | **6** |
| **LlamaIndex** | 8 | 7 | 8 | 7 | 4 | 8 | 6 | **6** |
| **CrewAI** | 7 | 6 | 7 | 5 | 3 | 6 | 5 | **5** |
| **DSPy** | 8 | 6 | 3 | 5 | 2 | 7 | 5 | **5/7*** |
| **AutoGen** | 7 | 5 | 6 | 6 | 5 | 7 | 4 | **5** |
| **Haystack** | 8 | 7 | 5 | 7 | 2 | 5 | 4 | **4** |

*DSPy: 5 as full replacement, 7 as inner optimization layer

### Key Insights from the Matrix

1. **A2A is the biggest differentiator.** Only Pydantic AI and Google ADK have native A2A protocol support. Since KAOS's core value proposition is Kubernetes-managed multi-agent orchestration with A2A, frameworks without A2A support require significant bridging work.

2. **Container/Operator compatibility is uniformly good.** All frameworks are Python libraries that run in containers. The differentiator is how naturally they accept env-var-based configuration.

3. **Memory is a secondary concern.** KAOS already has its own memory implementation. Framework memory is either redundant or complementary — it doesn't block integration.

4. **OTel alignment matters for production.** Frameworks with native OTel (Pydantic AI, Semantic Kernel) integrate more cleanly than those with proprietary observability (LangSmith, CrewAI Enterprise).

---

## Recommended Integration Approach

### Tier 1: Primary Targets (Build First)

#### 1. Pydantic AI — "The Natural Fit"

**Why:** Pydantic AI is architecturally the closest match to KAOS. It's a library (not a platform), uses pydantic-settings, has native A2A + MCP, and makes zero deployment assumptions. The integration surface is minimal.

**Integration Pattern: Adapter (Pattern C)**

```
KAOS Operator → creates Deployment
  → Container runs: kaos-pydanticai-adapter
    → Reads env vars (same pattern as kaos-framework)
    → Creates pydantic_ai.Agent with model, tools, MCP servers
    → Wraps with FastAPI server (or uses agent.to_a2a())
    → Exposes /health, /ready, /.well-known/agent, /v1/chat/completions
    → KAOS Memory adapter bridges sessions
    → KaosOtelManager or Logfire for telemetry
```

**Estimated effort:** 1-2 weeks for a working adapter
**Risk:** LOW — library-level integration with clear boundaries

#### 2. Google ADK — "The Protocol-Native Choice"

**Why:** Google ADK co-authored the A2A protocol, has the best memory abstraction alignment with KAOS (KAOS's memory was inspired by it), native MCP support, and official GKE deployment guides. It's the most "production-validated" option for Kubernetes deployment.

**Integration Pattern: Replace with Adapter (Pattern A/C hybrid)**

```
KAOS Operator → creates Deployment
  → Container runs: kaos-adk-adapter
    → Reads env vars
    → Creates google.adk.agents.Agent
    → ADK's api_server OR custom FastAPI wrapper
    → ADK's InMemorySessionService ↔ KAOS Memory bridge
    → ADK's A2A server for agent discovery/delegation
    → OTel instrumentation layer
```

**Estimated effort:** 2-3 weeks for a working adapter
**Risk:** LOW-MEDIUM — more moving parts than Pydantic AI but well-documented

### Tier 2: Secondary Targets (Build After Tier 1)

#### 3. LangChain/LangGraph — "The Ecosystem Play"

**Why:** Despite lower architecture fit, LangChain/LangGraph has the largest ecosystem, most community content, and is what many AI developers already know. Supporting it broadens KAOS's adoption potential.

**Integration Pattern: Wrap (Pattern B)**

```
KAOS Operator → creates Deployment
  → Container runs: kaos-langchain-adapter
    → KAOS server provides HTTP layer, A2A, memory, OTel
    → LangGraph provides agent logic (StateGraph)
    → Adapter bridges: KAOS messages ↔ LangGraph state
    → LangGraph tools ← MCP via langchain-mcp-adapters
    → Optional: LangSmith alongside KAOS OTel
```

**Estimated effort:** 3-4 weeks (A2A bridging is the hard part)
**Risk:** MEDIUM — two orchestration layers need careful boundary management

### Tier 3: Specialized / Deferred

| Framework | When to Integrate | Value Proposition |
|---|---|---|
| **DSPy** | When prompt optimization is needed | Inner layer: optimize prompts inside any framework agent |
| **LlamaIndex** | When RAG-heavy agents are needed | Best RAG capabilities; use as component inside agent |
| **Semantic Kernel** | When enterprise C#/Java teams need KAOS | Multi-language SDK; .NET ecosystem access |
| **CrewAI** | Probably never for KAOS | Fundamental multi-agent model mismatch |
| **AutoGen** | Probably never for KAOS | Distributed runtime conflicts with KAOS operator |
| **Haystack** | When pipeline-based RAG is needed | Good RAG pipeline components; use as inner component |

---

## Build Order Implications

### Phase 1: Framework Adapter Infrastructure
Before integrating any specific framework, KAOS needs:

1. **Adapter contract definition** — formalize the interface between KAOS operator and framework adapters:
   - Required HTTP endpoints (health, ready, agent card, chat completions)
   - Env var contract (which vars are guaranteed)
   - Memory interface (how adapters access KAOS memory)
   - OTel interface (how adapters participate in KAOS tracing)

2. **Container image strategy** — decide whether each framework adapter is:
   - A separate container image (recommended: `kaos-agent-pydanticai`, `kaos-agent-adk`, etc.)
   - A plugin loaded into a base image
   - User-provided images with adapter libraries

3. **CRD extension** — the Agent CRD may need a `spec.framework` field:
   ```yaml
   spec:
     framework: pydantic-ai  # or: adk, langchain, kaos (default)
     model: gpt-4o
     modelAPI: openai-proxy
   ```

### Phase 2: Pydantic AI Adapter
- Build adapter package: `kaos-adapter-pydanticai`
- Implement env var → Pydantic AI Agent mapping
- Implement A2A endpoint bridging (minor: `/.well-known/agent.json` vs `/.well-known/agent`)
- Bridge KAOS Memory ↔ Pydantic AI message_history
- Build container image
- Integration tests against KAOS operator
- **Dependencies:** Phase 1 adapter contract

### Phase 3: Google ADK Adapter
- Build adapter package: `kaos-adapter-adk`
- Implement env var → ADK Agent mapping
- Bridge ADK SessionService ↔ KAOS Memory (closest alignment of all frameworks)
- Leverage ADK's native A2A (may need minor protocol alignment)
- OTel instrumentation bridging
- Build container image
- Integration tests
- **Dependencies:** Phase 1 adapter contract

### Phase 4: LangChain/LangGraph Adapter
- Build adapter package: `kaos-adapter-langchain`
- Implement KAOS A2A wrapping around LangGraph agents (most work)
- Bridge LangGraph checkpointer ↔ KAOS Memory
- Handle LangSmith vs KAOS OTel coexistence
- Build container image
- Integration tests
- **Dependencies:** Phase 1 adapter contract, lessons from Phase 2/3

### Cross-Cutting: DSPy Integration
- DSPy doesn't need its own adapter — it's an inner optimization layer
- Provide `kaos-dspy-utils` package:
  - Utilities for running DSPy optimization against KAOS agents
  - Loading optimized DSPy programs into any framework adapter
  - Can be used inside Pydantic AI, ADK, or LangChain agents
- **Dependencies:** At least one framework adapter working

### Key Ordering Rationale

1. **Pydantic AI first** because it has the smallest integration surface and highest architectural alignment. Success here validates the adapter pattern with minimal risk.

2. **ADK second** because it has the best A2A/memory alignment but more moving parts. Lessons from Pydantic AI adapter inform this build.

3. **LangChain third** because it has the largest ecosystem but requires the most bridging work. By this point, the adapter pattern is proven and the A2A bridging patterns are established.

4. **DSPy cross-cutting** because it enhances any framework rather than replacing one. It can be integrated incrementally.

---

## Sources

| Source | Type | Confidence |
|---|---|---|
| KAOS source code (server.py, client.py, memory.py, telemetry/manager.py, agent_controller.go, agent_types.go) | Primary — read directly | HIGH |
| Pydantic AI docs (main, A2A, MCP pages) | Official docs via WebFetch | HIGH |
| Google ADK docs (quickstart, A2A intro) | Official docs via WebFetch | HIGH |
| AutoGen docs (main page) | Official docs via WebFetch | HIGH |
| Semantic Kernel docs (overview) | Official docs via WebFetch | MEDIUM-HIGH |
| LlamaIndex docs (landing page, structure) | Official docs via WebFetch | MEDIUM |
| Haystack docs (intro) | Official docs via WebFetch | MEDIUM |
| DSPy docs (main page) | Official docs via WebFetch | MEDIUM |
| CrewAI docs (introduction) | Official docs via WebFetch | MEDIUM |
| LangChain/LangGraph docs (overview) | Official docs via WebFetch | MEDIUM |
| Framework architecture internals (all) | Training data + inference | MEDIUM (flagged where uncertainty exists) |
