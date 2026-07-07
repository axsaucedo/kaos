# AgentServer

The AgentServer wraps a KAOS Agent in a FastAPI application with OpenAI-compatible chat API, A2A discovery, memory endpoints, and Kubernetes probes.

## Class Definition

```python
class AgentServer:
    def __init__(self, agent: Agent, settings: AgentServerSettings)
```

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/health` | GET | Kubernetes liveness probe |
| `/ready` | GET | Kubernetes readiness probe |
| `/.well-known/agent.json` | GET | A2A agent card discovery |
| `/v1/chat/completions` | POST | OpenAI-compatible chat (streaming + non-streaming) |
| `/` | POST | A2A JSON-RPC 2.0 endpoint (tasks/send, tasks/get, tasks/cancel) |
| `/memory/events` | GET | List memory events |
| `/memory/sessions` | GET | List memory sessions |

### POST /v1/chat/completions

OpenAI-compatible chat endpoint. Supports both streaming and non-streaming:

```bash
# Non-streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "agent", "messages": [{"role": "user", "content": "Hello!"}]}'

# Streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "agent", "messages": [{"role": "user", "content": "Hello!"}], "stream": true}'
```

### GET /.well-known/agent.json

A2A-compliant agent card (v0.3.0) with name, description, skills (discovered from MCP tools), capabilities, and version:

```bash
curl http://localhost:8000/.well-known/agent.json
```

### GET /memory/events

```bash
curl http://localhost:8000/memory/events?session_id=abc&limit=50
```

### POST / (A2A JSON-RPC)

A2A protocol-compliant JSON-RPC 2.0 endpoint for asynchronous task management.

**tasks/send** — Submit a task for async execution:
```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "id": 1,
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Analyze this data"}]
      }
    }
  }'
```

**tasks/get** — Poll task state:
```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tasks/get", "id": 2, "params": {"id": "task-uuid"}}'
```

**tasks/cancel** — Cancel a running task:
```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tasks/cancel", "id": 3, "params": {"id": "task-uuid"}}'
```

Task states: `submitted` → `working` → `completed` / `failed` / `canceled`

## AgentServerSettings

All configuration via environment variables:

```python
class AgentServerSettings(BaseSettings):
    agent_name: str                    # AGENT_NAME (required)
    model_api_url: str                 # MODEL_API_URL (required)
    model_name: str                    # MODEL_NAME (required)
    agent_description: str = "AI Agent"
    agent_instructions: str = "You are a helpful assistant."
    agent_port: int = 8000
    agent_log_level: str = "INFO"
    agent_access_log: bool = False

    # Sub-agents
    agent_sub_agents: str = ""         # "name:url,name:url"
    peer_agents: str = ""              # "worker-1,worker-2" (K8s format)

    # MCP servers
    mcp_servers: str = ""              # "echo,calc"
    # + MCP_SERVER_ECHO_URL, MCP_SERVER_CALC_URL

    # Agentic loop
    agentic_loop_max_steps: int = 5

    # Memory
    memory_enabled: bool = True
    memory_context_limit: int = 6
    memory_max_sessions: int = 1000
    memory_max_session_events: int = 500
    memory_store_endpoint: str = ""

    # TaskStore (A2A)
    task_store_type: str = "local"     # "local" or "null"
```

### Sub-Agent Formats

**Direct format** (`AGENT_SUB_AGENTS`):
```bash
export AGENT_SUB_AGENTS="worker-1:http://worker-1:8000,worker-2:http://worker-2:8000"
```

**Kubernetes format** (`PEER_AGENTS` + individual URLs):
```bash
export PEER_AGENTS="worker-1,worker-2"
export PEER_AGENT_WORKER_1_CARD_URL="http://worker-1:8000"
export PEER_AGENT_WORKER_2_CARD_URL="http://worker-2:8000"
```

### MCP Server Configuration

```bash
export MCP_SERVERS="echo,calc"
export MCP_SERVER_ECHO_URL="http://echo-mcp:8000"
export MCP_SERVER_CALC_URL="http://calc-mcp:8000"
```

URLs have `/mcp` auto-appended for Streamable HTTP transport.

## Factory Functions

### get_app

Lazy factory for uvicorn with `--factory`:

```bash
uvicorn pais.server:get_app --factory --host 0.0.0.0 --port 8000
```

### create_agent_server

```python
from pais.server import create_agent_server, AgentServerSettings

# From environment variables
server = create_agent_server()

# With explicit settings
settings = AgentServerSettings(
    agent_name="my-agent",
    model_api_url="http://ollama:11434",
    model_name="llama3.2",
)
server = create_agent_server(settings)
```

## Lifecycle

The server manages agent lifecycle via FastAPI lifespan:

```python
@asynccontextmanager
async def _lifespan(self, app: FastAPI):
    yield
    await self.agent.close()
```

## OpenTelemetry

When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the server automatically instruments:
- HTTP server spans (FastAPI)
- HTTP client spans (outgoing requests)
- Custom agent spans (tool calls, delegation)

```bash
export OTEL_SERVICE_NAME="my-agent"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4318"
```
