# Agentic Kubernetes Operator

A Kubernetes operator for deploying and managing AI agents with tool access and multi-agent coordination.

## Components

- **Agent**: AI agent pods with LLM access, MCP tools, and agent-to-agent delegation
- **ModelAPI**: LiteLLM proxy for LLM backends (Ollama, OpenAI, vLLM, etc.)
- **MCPServer**: Tool servers using Model Context Protocol

## Quick Start

### Prerequisites

- Kubernetes cluster (Docker Desktop, kind, etc.)
- kubectl configured
- Ollama running locally (optional, for local LLM)

### Install the Operator

```bash
cd operator
make deploy
```

### Deploy a Simple Agent

```yaml
# simple-agent.yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: my-agents

---
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: ollama-proxy
  namespace: my-agents
spec:
  mode: Proxy
  proxyConfig:
    env:
    - name: LITELLM_PROXY_API_BASE
      value: "http://host.docker.internal:11434"

---
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
  namespace: my-agents
spec:
  type: python-runtime
  config:
    mcp: "test-mcp-echo-server"

---
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: my-agent
  namespace: my-agents
spec:
  modelAPI: ollama-proxy
  mcpServers:
  - echo-tools
  config:
    description: "My first agent"
    instructions: "You are a helpful assistant with echo tools."
    env:
    - name: MODEL_NAME
      value: "smollm2:135m"
```

Apply it:

```bash
kubectl apply -f simple-agent.yaml
```

### Interact with the Agent

Port-forward to the agent:

```bash
kubectl port-forward -n my-agents svc/my-agent 8000:80
```

Send a request:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-agent",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Multi-Agent Setup

Agents can delegate tasks to other agents using the `agentNetwork` field:

```yaml
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: coordinator
  namespace: my-agents
spec:
  modelAPI: ollama-proxy
  config:
    description: "Coordinator agent"
    instructions: "Delegate tasks to worker agents."
  agentNetwork:
    expose: true
    access:
    - worker-1
    - worker-2

---
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: worker-1
  namespace: my-agents
spec:
  modelAPI: ollama-proxy
  config:
    description: "Worker agent 1"
  agentNetwork:
    expose: true
```


## Development

### Run Python Tests

```bash
cd python
uv sync
uv run pytest tests/ -v
```

### Run Operator Locally

```bash
cd operator
make deploy
```

### Run E2E Tests

```bash
cd operator/tests
uv sync
uv run pytest e2e/ -v
```

## Sample Configurations

See `operator/config/samples/` for example configurations:

1. `1-simple-echo-agent.yaml` - Single agent with echo MCP tool (hosted Ollama in-cluster)
2. `2-multi-agent-mcp.yaml` - Coordinator with worker agents (hosted Ollama in-cluster)
3. `3-hierarchical-agents.yaml` - Multi-level agent hierarchy with calculator tools
4. `4-dev-ollama-proxy-agent.yaml` - Development setup with proxy to host Ollama

For local development with Ollama running on your host machine, use sample 4 which uses `LITELLM_PROXY_API_BASE` to connect to `http://host.docker.internal:11434`.

