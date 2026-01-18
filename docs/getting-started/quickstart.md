# Quick Start Guide

Deploy your first AI agent on Kubernetes in under 5 minutes.

## Prerequisites

- Kubernetes cluster (Docker Desktop, kind, minikube, or cloud)
- kubectl configured and connected

Choose your preferred interface:

- **Option A (CLI/UI)**: Install `kaos-cli` via pip
- **Option B (Helm/kubectl)**: Install Helm 3.x

---

## Option A: KAOS CLI & UI

The easiest way to get started with KAOS.

### Step 1: Install the CLI

```bash
pip install kaos-cli
```

### Step 2: Install the Operator

```bash
kaos install
```

This installs the KAOS operator to your cluster using the published Helm chart.

### Step 3: Open the UI

```bash
kaos ui
```

This starts a local proxy and opens the KAOS UI in your browser.

### Step 4: Create Your First Agent

In the UI:
1. Navigate to **Agents** → **Create Agent**
2. Fill in the agent details
3. Select a ModelAPI (or create one)
4. Click **Create**

Or use the CLI to apply a YAML file:

```bash
kubectl apply -f my-agent.yaml
```

### Next Steps

- [CLI Commands](/cli/commands) - Full CLI reference
- [UI Features](/ui/features) - Explore the UI

---

## Option B: Helm & kubectl

For users who prefer direct Kubernetes tooling.

### Step 1: Install the Operator

```bash
# Add the KAOS Helm repository
helm repo add kaos https://axsaucedo.github.io/kaos/charts
helm repo update

# Install the operator
helm install kaos kaos/kaos-operator -n kaos-system --create-namespace
```

Verify the operator is running:

```bash
kubectl get pods -n kaos-system
# Expected: kaos-controller-manager-xxx  Running
```

### Step 2: Deploy a Simple Agent

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
  hostedConfig:
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
    env:
      - name: MODEL_NAME
        value: "ollama/smollm2:135m"
```

Apply it:

```bash
kubectl apply -f my-agent.yaml
```

### Step 3: Wait for Resources

```bash
# Watch resources become ready
kubectl get agent,modelapi -n my-agents -w

# Expected output after ~60s:
# NAME                        READY   PHASE
# agent.kaos.tools/my-agent   true    Ready
# 
# NAME                         READY   PHASE
# modelapi.kaos.tools/ollama   true    Ready
```

### Step 4: Interact with the Agent

Port-forward to the agent service:

```bash
kubectl port-forward -n my-agents svc/agent-my-agent 8000:8000
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

---

## Adding MCP Tools

Extend your agent with tools by adding an MCPServer:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
  namespace: my-agents
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        def echo(message: str) -> str:
            """Echo back the message."""
            return f"Echo: {message}"
```

Then update your Agent to reference it:

```yaml
spec:
  mcpServers:
    - echo-tools
```

## Next Steps

- [Concepts](./concepts) - Understand the architecture
- [Multi-Agent Tutorial](/tutorials/multi-agent) - Build agent teams
- [Custom MCP Tools](/tutorials/custom-mcp-tools) - Create your own tools
