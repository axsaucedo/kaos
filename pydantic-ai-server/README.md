# 🥧 PAIS: Pydantic AI Server

<p align="center">
  <strong>Enterprise server wrapper for Pydantic AI agents on Kubernetes</strong>
</p>

<p align="center">
  <img src="pais-horizontal.jpg" alt="PAIS Logo — A pie with a π symbol on top of a rocket" height="300">
</p>

<p align="center">
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-%3E%3D3.12-blue" alt="Python"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/pydantic--ai-powered-green" alt="Pydantic AI"></a>
</p>

---

PAIS wraps [Pydantic AI](https://ai.pydantic.dev) agents with production server capabilities: OpenAI-compatible HTTP API, distributed memory, multi-agent delegation, health probes, A2A discovery, and OpenTelemetry instrumentation.

## Architecture

```mermaid
graph TD
    Client([Client]) -->|POST /v1/chat/completions| Server[AgentServer]

    subgraph PAIS["🥧 PAIS"]
        Server --> Agent[Pydantic AI Agent]
        Server --> Memory[(Memory<br/>Local / Redis)]
        Agent --> Delegation[DelegationToolset]
        Agent --> MCP[MCP Servers]
    end

    Agent -->|LLM calls| ModelAPI[Model API]
    Delegation -->|HTTP| SubAgent([Sub-Agents])
    MCP -->|Streamable HTTP| MCPSrv([MCP Tool Servers])

    Server -->|GET /health /ready| K8s([Kubernetes])
    Server -->|GET /.well-known/agent.json| A2A([A2A Discovery])
```

## Quick Start

### Installation

```bash
pip install pydantic-ai-server         # Library only
pip install pydantic-ai-server[cli]    # With CLI (includes kaos-cli)
```

### SDK Usage

Create a custom agent with pure Pydantic AI — zero boilerplate:

```python
# server.py
from pydantic_ai import Agent

agent = Agent(
    model="test",
    instructions="You are a helpful assistant.",
    defer_model_check=True,
)

@agent.tool_plain
def greet(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"
```

Run it locally:

```bash
AGENT_NAME=my-agent MODEL_API_URL=http://localhost:11434 MODEL_NAME=llama3.2 \
  pais run
```

The `pais run` CLI auto-discovers your `Agent` and wraps it with PAIS (health probes, A2A card, memory, OpenAI-compatible API).

For explicit ASGI app creation (e.g., custom middleware):

```python
from pais import serve
app = serve(agent)  # Returns FastAPI ASGI app
```

### CLI Quick Start

Scaffold, build, and deploy a custom agent:

```bash
# 1. Scaffold a new agent project
pais init my-agent    # or: kaos agent init my-agent
cd my-agent

# 2. Edit server.py — add your tools and logic

# 3. Run locally
pais run              # or: kaos agent run

# 4. Build the Docker image
pais build --name my-agent --tag v1    # or: kaos agent build ...

# 5. Deploy to Kubernetes
kaos agent deploy my-agent --modelapi my-api --model llama3.2
```

For KIND clusters, add `--kind-load` to load the image directly:

```bash
kaos agent build --name my-agent --tag v1 --kind-load
```

## Module Structure

```
pais/
├── server.py       # AgentServer, create_agent_server(), routes, logging
├── serverutils.py  # AgentDeps, AgentCard, RemoteAgent, AgentServerSettings, model resolution
├── tools.py        # DelegationToolset, string-mode handler, progress events
├── memory.py       # Memory ABC, LocalMemory, RedisMemory, NullMemory
└── telemetry.py    # OpenTelemetry setup, SERVICE_NAME, metrics
```

## Development

```bash
cd pydantic-ai-server
source .venv/bin/activate
make format          # black .
make lint            # black --check . && ty check
python -m pytest tests/ -v
```

## Configuration Reference

All settings are environment variables (via `pydantic-settings`):

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_NAME` | ✅ | Agent name |
| `MODEL_API_URL` | ✅ | LLM API base URL |
| `MODEL_NAME` | ✅ | Model identifier |
| `AGENT_INSTRUCTIONS` | | System prompt |
| `AGENT_SUB_AGENTS` | | Sub-agents: `name:url,name:url` |
| `MCP_SERVERS` | | Comma-separated MCP server names |
| `MCP_SERVER_<NAME>_URL` | | URL for each MCP server |
| `MEMORY_TYPE` | | `local` (default), `redis`, or `null` |
| `MEMORY_REDIS_URL` | | Redis URL (when `MEMORY_TYPE=redis`) |
| `TOOL_CALL_MODE` | | `auto` (default), `native`, `string` |
| `OTEL_ENABLED` | | Enable OpenTelemetry |

## Features

| Feature | Description |
|---------|-------------|
| **OpenAI-Compatible API** | `/v1/chat/completions` endpoint (streaming + non-streaming) |
| **Distributed Memory** | Local, Redis, or NullMemory backends with session persistence |
| **Multi-Agent Delegation** | Sub-agent orchestration via `DelegationToolset` |
| **MCP Tool Integration** | Connect to MCP servers via Streamable HTTP |
| **A2A Discovery** | `/.well-known/agent.json` A2A-compliant card for agent-to-agent communication |
| **Health Probes** | `/health` and `/ready` endpoints for Kubernetes |
| **OpenTelemetry** | Tracing, metrics, and log correlation out of the box |
| **String Mode** | Tool calling for models without native function calling |
| **Custom Agents** | Wrap your own Pydantic AI agent with `create_agent_server()` |

## License

Apache 2.0 — see [LICENSE](../../LICENSE).
