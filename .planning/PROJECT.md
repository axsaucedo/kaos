# KAOS Python Framework Refactor — Framework Evaluation

## What This Is

A research and evaluation project to determine which agentic AI framework (if any) should replace KAOS's custom Python data-plane code. KAOS is a Kubernetes-native agent orchestration platform with a Go operator (control plane) and a Python agent runtime (data plane). The Python side currently has a custom agentic loop, distributed memory (Local/Redis/Null), MCP tool integration, OpenTelemetry observability, and agent-to-agent communication. This project evaluates whether adopting an existing framework would improve the platform and recommends the best path forward.

## Core Value

Identify the framework (or "stay custom" decision) that best serves KAOS's mission: provider-agnostic, Kubernetes-native agent orchestration with distributed memory, observability, flexible A2A communication, and the ability for users to build custom agent images or use KAOS defaults.

## Requirements

### Validated

- ✓ Custom agentic loop with tool calling (native + string parsing modes) — existing
- ✓ OpenAI-compatible HTTP API (`/v1/chat/completions`) — existing
- ✓ MCP tool integration via FastMCP SDK — existing
- ✓ Distributed memory (LocalMemory, RedisMemory, NullMemory) — existing
- ✓ OpenTelemetry observability (traces, metrics, logs via OTLP) — existing
- ✓ Agent-to-agent delegation via `/v1/chat/completions` — existing
- ✓ A2A discovery endpoint (`/.well-known/agent`) — existing
- ✓ Streaming support (SSE) — existing
- ✓ LiteLLM-based model routing (provider-agnostic) — existing
- ✓ Custom image override (users build own agent containers) — existing

### Active

- [ ] Evaluate Pydantic AI as framework foundation
- [ ] Evaluate LangChain/LangGraph as framework foundation
- [ ] Evaluate CrewAI as framework foundation
- [ ] Evaluate Google ADK (with known GCP lock-in concerns)
- [ ] Evaluate select other frameworks (AutoGen, Semantic Kernel, LlamaIndex, etc.)
- [ ] Assess distributed memory support/compatibility per framework
- [ ] Assess OTel observability integration per framework
- [ ] Assess A2A communication flexibility per framework
- [ ] Assess MCP tool integration per framework
- [ ] Assess provider agnosticism per framework
- [ ] Assess user extensibility (custom agent images) per framework
- [ ] Produce framework comparison matrix with recommendation

### Out of Scope

- Actual refactoring or code changes — research and recommendation only
- Go operator changes — focus is Python data-plane
- CLI changes — focus is agent runtime framework
- Documentation site changes

## Context

KAOS was originally built with the assumption that Google ADK would be adopted as the agent framework. After evaluation, ADK was found to be too tightly coupled to GCP and Vertex AI — particularly its memory implementations (distributed memory was GCP-specific) and its A2A protocol implementation was inflexible and over-abstracted. The custom Python implementation was built instead.

The current custom code works but has complexity hotspots (client.py at 993 lines, memory.py at 726 lines, server.py at 705 lines). A well-chosen framework could reduce maintenance burden, provide battle-tested patterns, and offer a better developer experience for users building custom agents.

Key concerns from ADK experience:
- A2A protocol implementations that add too much abstraction and then don't work in practice
- Memory implementations locked to specific cloud providers
- Frameworks that claim provider-agnostic but default to one vendor's ecosystem

The evaluation must be practical — what actually works vs. what's marketed.

### Current Architecture (Python Data-Plane)

- **Agent (`agent/client.py`)**: Core agentic loop — two-phase execution (tool loop then final response), supports native and string-parsed tool calling
- **AgentServer (`agent/server.py`)**: FastAPI HTTP server with OpenAI-compatible API, memory management, A2A discovery
- **Memory (`agent/memory.py`)**: Session-scoped conversation history — LocalMemory (in-process), RedisMemory (distributed), NullMemory (stateless)
- **MCPClient (`mcptools/client.py`)**: MCP-protocol tool client using official SDK
- **ModelAPI Client (`modelapi/client.py`)**: OpenAI-compatible async HTTP client via httpx, supports streaming
- **Telemetry (`telemetry/manager.py`)**: Singleton OTel manager with span/metric management, OTLP export

### Key Integration Points

- Operator injects env vars into agent pods (model URL, MCP server URLs, peer agent URLs, memory config, OTel config)
- Agent discovers peers via `AGENT_NETWORK_{NAME}_URL` env vars, creates delegation tools dynamically
- MCP servers connected via Streamable HTTP transport
- Memory keyed by `x-session-id` header
- All components export telemetry to OTLP collector when enabled

## Constraints

- **Provider agnosticism**: Must work with any LLM provider (OpenAI, Anthropic, local models, etc.) — no cloud vendor lock-in
- **Kubernetes-native**: Must work as containerized pods managed by the existing Go operator
- **Distributed memory**: Redis-backed distributed memory across agent instances is essential
- **Observability**: OpenTelemetry integration (traces, metrics, logs) is non-negotiable
- **A2A communication**: Agent-to-agent communication is must-have; A2A protocol support desired but must be flexible, not over-abstracted
- **Clean slate OK**: Architecture can change completely — no requirement to preserve current patterns
- **User extensibility**: Users must be able to build custom agent images (similar to FastMCP pattern)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Rejected Google ADK | GCP/Vertex AI lock-in in memory and A2A; inflexible abstractions | ✓ Good — avoided vendor lock-in |
| Custom Python agent code | Built when no framework met requirements | ⚠️ Revisit — evaluating alternatives |
| LiteLLM for model routing | Provider-agnostic LLM access | ✓ Good — works well |
| FastMCP for MCP integration | Standard MCP SDK | ✓ Good — clean integration |
| Redis for distributed memory | Simple, widely available | ✓ Good — but framework compatibility TBD |

---
*Last updated: 2026-02-20 after initialization*
