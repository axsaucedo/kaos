# YAAY: Yet Another Agentic System

<p align="center">
  <strong>🎉 The simplest way to deploy AI agents on Kubernetes</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#multi-agent-with-gateway-api">Multi-Agent</a> •
  <a href="#documentation">Documentation</a>
</p>

---

**YAAY** makes deploying AI agents on Kubernetes as simple as writing YAML. Define your agents, connect them to tools, and let Kubernetes handle the rest.

## Features

- **🤖 Agent CRD** - Deploy AI agents as native Kubernetes resources
- **🔧 MCP Tools** - Integrate tools using Model Context Protocol
- **🔗 Multi-Agent Networks** - Build hierarchical agent systems with automatic delegation
- **🌐 Gateway API** - Expose agents via Kubernetes Gateway API
- **📡 OpenAI-Compatible** - All agents expose `/v1/chat/completions` endpoints
- **🔄 Agentic Loop** - Built-in reasoning loop with tool calling and delegation

## Quick Start

### Prerequisites

- Kubernetes cluster (Docker Desktop, kind, minikube)
- kubectl configured
- Helm 3.x

### Install YAAY Operator

```bash
cd operator
helm install kaos-operator chart/ -n kaos-system --create-namespace
```

### Deploy Your First Agent

```yaml
# simple-agent.yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
spec:
  mode: Hosted
  hostedConfig:
    model: "smollm2:135m"

---
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
spec:
  type: python-runtime
  config:
    mcp: "test-mcp-echo-server"

---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: assistant
spec:
  modelAPI: ollama
  mcpServers:
    - echo-tools
  config:
    description: "AI assistant with echo tools"
    instructions: "You are a helpful assistant. Use the echo tool when asked to repeat something."
    env:
      - name: MODEL_NAME
        value: "ollama/smollm2:135m"
```

```bash
kubectl apply -f simple-agent.yaml

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=assistant --timeout=120s

# Port-forward and test
kubectl port-forward svc/assistant 8000:80
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "assistant", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## Multi-Agent with Gateway API

YAAY supports complex multi-agent systems with Gateway API for external access:

```yaml
# multi-agent-gateway.yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
spec:
  mode: Hosted
  hostedConfig:
    model: "llama3.2:latest"

---
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: search-tools
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        def web_search(query: str) -> str:
            """Search the web for information."""
            return f"Results for: {query}"

---
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: calculator
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        def calculate(expression: str) -> str:
            """Evaluate a mathematical expression."""
            return str(eval(expression))

---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: coordinator
spec:
  modelAPI: ollama
  config:
    description: "Coordinator that delegates to specialist agents"
    instructions: |
      You are a coordinator. Delegate research tasks to researcher,
      and calculations to analyst.
  agentNetwork:
    access:
      - researcher
      - analyst
  gatewayRoute:
    timeout: "120s"

---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: researcher
spec:
  modelAPI: ollama
  mcpServers:
    - search-tools
  config:
    description: "Research specialist with web search"
    instructions: "You are a researcher. Use web_search to find information."

---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: analyst
spec:
  modelAPI: ollama
  mcpServers:
    - calculator
  config:
    description: "Data analyst with calculation tools"
    instructions: "You are an analyst. Use calculate for math operations."
```

With Gateway API enabled, agents are accessible via:
```
http://<gateway-ip>/coordinator/v1/chat/completions
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       YAAY Operator                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Agent     │  │  MCPServer  │  │  ModelAPI   │              │
│  │ Controller  │  │ Controller  │  │ Controller  │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
└─────────┼────────────────┼────────────────┼─────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   Agent Pod     │ │  MCP Server Pod │ │ Ollama (Hosted) │
│  ┌───────────┐  │ │  ┌───────────┐  │ │  ┌───────────┐  │
│  │  Agent    │  │ │  │ MCP Tools │  │ │  │  Ollama   │  │
│  │  Runtime  │──┼─┼─►│  Server   │  │ │  │  + Model  │  │
│  └───────────┘  │ │  └───────────┘  │ │  └───────────┘  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Development

```bash
# Python tests
cd python && uv sync && uv run pytest tests/ -v

# Go tests  
cd operator && make test

# E2E tests (requires kind)
cd operator && make kind-e2e
```

## Documentation

📚 **[Full Documentation](https://axsaucedo.github.io/yaay)**

- [Getting Started](https://axsaucedo.github.io/yaay/getting-started/quickstart)
- [Agent CRD Reference](https://axsaucedo.github.io/yaay/operator/agent-crd)
- [Multi-Agent Tutorial](https://axsaucedo.github.io/yaay/tutorials/multi-agent)

## Sample Configurations

See [`operator/config/samples/`](operator/config/samples/) for examples:

1. **Simple Agent** - Single agent with echo MCP tool
2. **Multi-Agent** - Coordinator with worker agents
3. **Hierarchical** - Multi-level agent hierarchy
4. **Custom Tools** - Dynamic tool creation with `tools.fromString`

## License

Apache 2.0
