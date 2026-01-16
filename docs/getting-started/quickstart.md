# Quick Start Guide

Deploy your first AI agent on Kubernetes in under 5 minutes.

## Prerequisites

- Kubernetes cluster (Docker Desktop, kind, minikube, or cloud)
- kubectl configured and connected
- Helm 3.x installed

## Step 1: Install the Operator

```bash
# Clone the repository
git clone https://github.com/axsaucedo/kaos.git
cd kaos/operator

# Install with Helm
helm install kaos-operator chart/ -n kaos-system --create-namespace

# Optional: Enable Gateway API for external access
# helm install kaos-operator chart/ -n kaos-system --create-namespace \
#   --set gatewayAPI.enabled=true \
#   --set gatewayAPI.createGateway=true \
#   --set gatewayAPI.gatewayClassName=envoy-gateway
```

Verify the operator is running:

```bash
kubectl get pods -n kaos-system
# Expected: kaos-operator-controller-manager-xxx  Running
```

## Step 2: Deploy a Simple Agent

Create a file `my-agent.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: my-agents

---
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
  namespace: my-agents
spec:
  mode: Hosted
  serverConfig:
    model: "smollm2:135m"

---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
  namespace: my-agents
spec:
  modelAPI: ollama
  config:
    description: "My first agent"
    instructions: "You are a helpful assistant."
  agentNetwork:
    expose: true
```

Apply it:

```bash
kubectl apply -f my-agent.yaml
```

## Step 3: Wait for Resources

```bash
# Watch resources become ready
kubectl get agent,modelapi -n my-agents -w

# Expected output after ~60s:
# NAME                           MODELAPI   READY   PHASE
# agent.kaos.tools/my-agent   ollama     true    Ready
# 
# NAME                               MODE     READY   PHASE
# modelapi.kaos.tools/ollama   Hosted   true    Ready
```

## Step 4: Interact with the Agent

Port-forward to the agent service:

```bash
kubectl port-forward -n my-agents svc/my-agent 8000:80
```

Send a message:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-agent",
    "messages": [{"role": "user", "content": "Hello! What can you do?"}]
  }'
```

## Step 5: Add MCP Tools

Extend your agent with tools by adding an MCPServer:

```yaml
---
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
  namespace: my-agents
spec:
  type: python-runtime
  config:
    mcp: "test-mcp-echo-server"

---
# Update Agent to reference the MCP server
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
  namespace: my-agents
spec:
  modelAPI: ollama
  mcpServers:
  - echo-tools  # Add this line
  config:
    description: "Agent with echo tools"
    instructions: "You are a helpful assistant with access to an echo tool."
    agenticLoop:
      maxSteps: 5
      enableTools: true
  agentNetwork:
    expose: true
```

## Next Steps

- [Concepts](concepts.md) - Understand the architecture
- [Multi-Agent Coordination](../tutorials/multi-agent.md) - Build agent teams
- [Custom MCP Tools](../tutorials/custom-mcp-tools.md) - Create your own tools
- [Samples](../../operator/config/samples/) - More example configurations
