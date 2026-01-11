# AgentServer

The AgentServer class provides a FastAPI server that exposes agent functionality via HTTP endpoints.

## Class Definition

```python
class AgentServer:
    def __init__(
        self,
        agent: Agent,
        port: int = 8000,
        debug_memory_endpoints: bool = False
    )
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `agent` | Agent | Yes | - | Agent instance to serve |
| `port` | int | No | 8000 | Server port |
| `debug_memory_endpoints` | bool | No | False | Enable `/memory/*` endpoints |

## Endpoints

### Health Probes

#### GET /health

Kubernetes liveness probe.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "name": "my-agent",
  "timestamp": 1704067200
}
```

#### GET /ready

Kubernetes readiness probe.

```bash
curl http://localhost:8000/ready
```

```json
{
  "status": "ready",
  "name": "my-agent",
  "timestamp": 1704067200
}
```

### A2A Protocol

#### GET /.well-known/agent

Agent discovery endpoint (A2A protocol).

```bash
curl http://localhost:8000/.well-known/agent
```

```json
{
  "name": "my-agent",
  "description": "A helpful assistant",
  "url": "http://localhost:8000",
  "skills": [
    {
      "name": "echo",
      "description": "Echo the input text",
      "parameters": {"text": {"type": "string"}}
    }
  ],
  "capabilities": [
    "message_processing",
    "task_execution",
    "tool_execution"
  ]
}
```

#### POST /agent/invoke

Task invocation endpoint (A2A protocol).

```bash
curl -X POST http://localhost:8000/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"task": "Echo hello world"}'
```

```json
{
  "response": "Echo: hello world",
  "status": "completed"
}
```

### OpenAI-Compatible API

#### POST /v1/chat/completions

OpenAI-compatible chat completions endpoint.

**Non-Streaming:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-agent",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1704067200,
  "model": "my-agent",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

**Streaming:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-agent",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

Returns Server-Sent Events (SSE):

```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### Agent Delegation

Delegation happens automatically via the agentic loop when the model's response contains a `delegate` block:

```
```delegate
{"agent": "worker-1", "task": "Process this data"}
```
```

The agent parses this and invokes the sub-agent via `/v1/chat/completions`. For deterministic testing, use `DEBUG_MOCK_RESPONSES` environment variable to control model responses.

### Debug Endpoints

Only available when `debug_memory_endpoints=True`.

#### GET /memory/events

List all memory events across sessions.

```bash
curl http://localhost:8000/memory/events
```

```json
{
  "agent": "my-agent",
  "events": [
    {
      "event_id": "event_abc123",
      "timestamp": "2024-12-31T12:00:00",
      "event_type": "user_message",
      "content": "Hello!",
      "metadata": {}
    }
  ],
  "total": 1
}
```

#### GET /memory/sessions

List all session IDs.

```bash
curl http://localhost:8000/memory/sessions
```

```json
{
  "agent": "my-agent",
  "sessions": ["session_abc123"],
  "total": 1
}
```

## Factory Functions

### create_agent_server

Create server from settings with automatic sub-agent parsing.

```python
from agent.server import create_agent_server, AgentServerSettings

# From environment variables
server = create_agent_server()

# With explicit settings
settings = AgentServerSettings(
    agent_name="my-agent",
    model_api_url="http://localhost:8000",
    model_name="smollm2:135m"
)
server = create_agent_server(settings)
```

### create_app

Create FastAPI app for uvicorn deployment.

```python
from agent.server import create_app

app = create_app()
```

### get_app

Lazy app factory for uvicorn with `--factory` flag.

```bash
uvicorn agent.server:get_app --factory --host 0.0.0.0 --port 8000
```

## AgentServerSettings

Configuration via environment variables.

```python
class AgentServerSettings(BaseSettings):
    # Required
    agent_name: str
    model_api_url: str
    
    # Optional with defaults
    model_name: str = "smollm2:135m"
    agent_description: str = "AI Agent"
    agent_instructions: str = "You are a helpful assistant."
    agent_port: int = 8000
    agent_log_level: str = "INFO"
    
    # Sub-agents (direct format)
    agent_sub_agents: str = ""  # "name:url,name:url"
    
    # Sub-agents (Kubernetes format)
    peer_agents: str = ""  # "worker-1,worker-2"
    # + PEER_AGENT_WORKER_1_CARD_URL env var
    
    # Agentic loop
    agentic_loop_max_steps: int = 5
    agentic_loop_enable_tools: bool = True
    agentic_loop_enable_delegation: bool = True
    
    # Debug
    agent_debug_memory_endpoints: bool = False
```

## Running the Server

### Programmatic

```python
from agent.client import Agent
from agent.server import AgentServer
from modelapi.client import ModelAPI

model_api = ModelAPI(model="smollm2:135m", api_base="http://localhost:8000")
agent = Agent(name="my-agent", model_api=model_api)
server = AgentServer(agent, port=8080)

server.run(host="0.0.0.0")
```

### Via Environment Variables

```bash
export AGENT_NAME="my-agent"
export MODEL_API_URL="http://localhost:8000"
export AGENT_INSTRUCTIONS="You are helpful."

uvicorn agent.server:get_app --factory --host 0.0.0.0 --port 8000
```

### Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -e .

CMD ["uvicorn", "agent.server:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

## Lifecycle

The server manages agent lifecycle:

```python
@asynccontextmanager
async def _lifespan(self, app: FastAPI):
    logger.info("AgentServer startup")
    yield
    logger.info("AgentServer shutdown")
    await self.agent.close()  # Cleanup on shutdown
```

## Error Handling

All endpoints return appropriate HTTP status codes:

| Status | Description |
|--------|-------------|
| 200 | Success |
| 400 | Bad request (missing/invalid parameters) |
| 404 | Not found (sub-agent not found for delegation) |
| 500 | Internal error (processing failed) |

Error response format:

```json
{
  "detail": "Error message here"
}
```
