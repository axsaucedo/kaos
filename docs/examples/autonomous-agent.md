---
jupyter:
  jupytext:
    cell_metadata_filter: -all
    text_representation:
      extension: .md
      format_name: markdown
      format_version: '1.3'
      jupytext_version: 1.19.1
  kernelspec:
    display_name: Python 3 (ipykernel)
    language: python
    name: python3
---

# Autonomous Agent Execution

> **Try it yourself!** This example is available as an executable [Jupyter notebook](/examples/autonomous-agent.ipynb).

This example demonstrates **autonomous (self-looping) agent execution** in KAOS. Autonomous agents iteratively work toward a goal by calling tools and reasoning across multiple iterations, without requiring human messages between each step.

## How Autonomous Execution Works

Traditional agent interaction is request-response:

```
User: "Check system health"  ->  Agent runs once  ->  Response
```

Autonomous agents self-loop until the goal is achieved:

```
Goal: "Check system health and fix issues"
  Iteration 1: Agent calls health_check tool  ->  finds issue
  Iteration 2: Agent calls fix_service tool   ->  fixes issue
  Iteration 3: Agent calls health_check again ->  all clear, done!
```

Autonomous execution is activated by setting a `goal` in the Agent CRD's `spec.config.autonomous` section. When the agent pod starts, it immediately begins working toward the goal in a self-loop with configurable intervals between iterations.

## Prerequisites

- A running Kubernetes cluster with KAOS operator installed
- `kaos` CLI installed and configured
- `kubectl` configured for the cluster

## Setup

```python
import os
import subprocess
import json
import time

NAMESPACE = "autonomous-example"
os.environ["NAMESPACE"] = NAMESPACE
```

```python
subprocess.run(
    ["kubectl", "create", "namespace", NAMESPACE],
    capture_output=True, text=True,
)
subprocess.run(
    ["kubectl", "config", "set-context", "--current", f"--namespace={NAMESPACE}"],
    check=True, capture_output=True, text=True,
)
print(f"✅ Namespace '{NAMESPACE}' ready")
```

## Step 1: Create a ModelAPI

Create a ModelAPI in Proxy mode. We use mock responses so no real LLM is needed:

```python
result = subprocess.run(
    ["kaos", "modelapi", "deploy", "auto-api", "--mode", "Proxy", "--wait"],
    capture_output=True, text=True, check=True,
)
print("✅ ModelAPI 'auto-api' deployed")
```

## Step 2: Create an MCP Server (Echo Tool)

Deploy a simple echo MCP server that the agent can call as a tool:

```python
echo_func = '''
def echo(message: str) -> str:
    """Echo the provided message back."""
    return f"Echo: {message}"
'''

result = subprocess.run(
    ["kaos", "mcp", "deploy", "auto-echo",
     "--runtime", "python-string",
     "--params", echo_func,
     "--wait"],
    capture_output=True, text=True, check=True,
)
print("✅ MCP Server 'auto-echo' deployed")
```

## Step 3: Deploy an Autonomous Agent

Deploy an agent with autonomous mode enabled. The `--autonomous` flag sets the goal, and `--auto-interval` controls the pause between iterations. Mock responses simulate two iterations of tool usage:

```python
mock1 = json.dumps({
    "tool_calls": [{
        "id": "call_1",
        "name": "echo",
        "arguments": {"message": "checking system status"}
    }]
})
mock2 = "System check complete. Echo confirmed: checking system status. Goal achieved."

result = subprocess.run(
    ["kaos", "agent", "deploy", "auto-agent",
     "--modelapi", "auto-api",
     "--model", "gpt-4o",
     "--mcp", "auto-echo",
     "--instructions", "You are a test agent. Use the echo tool when asked.",
     "--mock-response", mock1,
     "--mock-response", mock2,
     "--autonomous", "Use the echo tool to check system status and report the result",
     "--auto-interval", "1",
     "--wait"],
    capture_output=True, text=True, check=True,
)
print("✅ Autonomous agent 'auto-agent' deployed")
```

The agent starts its autonomous loop immediately on pod boot:
- **Iteration 1**: Calls the `echo` tool with "checking system status"
- **Iteration 2**: Receives mock text response (no tool calls) → loop completes

## Step 4: Verify Autonomous Execution via Memory

The agent runs autonomously on startup. Give it a moment, then check that memory recorded the execution:

```python
time.sleep(8)

result = subprocess.run(
    ["kaos", "agent", "memory", "auto-agent", "--json"],
    capture_output=True, text=True, check=True,
)
data = json.loads(result.stdout)
events = data.get("events", [])
assert len(events) >= 2, f"Expected at least 2 memory events, got {len(events)}"

types = [e["event_type"] for e in events]
assert "user_message" in types, "Missing goal user_message"
assert "agent_response" in types, "Missing agent_response"

print(f"✅ Autonomous session recorded: {len(events)} events")
for e in events:
    content = str(e.get("content", ""))[:80]
    print(f"  [{e['event_type']}] {content}")
```

## Step 5: Verify Agent Card

Check the agent's A2A card to confirm it's healthy and has discovered the echo tool:

```python
result = subprocess.run(
    ["kaos", "agent", "status", "auto-agent", "--json"],
    capture_output=True, text=True, check=True,
)
card = json.loads(result.stdout)

assert "jsonrpc" in card.get("supportedProtocols", []), "Missing A2A protocol support"
skills = [s["name"] for s in card.get("skills", [])]
assert "echo" in skills, f"Echo tool not found in skills: {skills}"

print(f"✅ Agent healthy: {len(skills)} tool(s), A2A enabled")
print(f"  Skills: {skills}")
```

## Step 6: Send a Sync A2A Message

Even though the agent is autonomous, you can still send interactive messages via A2A. This uses the sync (default) mode:

```python
result = subprocess.run(
    ["kaos", "agent", "a2a", "send", "auto-agent",
     "--message", "Say hello via A2A",
     "--json"],
    capture_output=True, text=True, check=True,
)
data = json.loads(result.stdout)
task = data.get("result", {})
state = task.get("status", {}).get("state")

assert state == "completed", f"Expected completed, got {state}"

history = task.get("history", [])
agent_msgs = [h for h in history if h.get("role") == "agent"]
assert len(agent_msgs) > 0, "No agent response in history"

print(f"✅ A2A sync message completed: {state}")
print(f"  Agent response: {agent_msgs[0]['parts'][0]['text'][:100]}")
```

## Production Setup: Kubernetes Cluster Monitor

The simple example above demonstrates the mechanics. For production autonomous agents, you need:
- **RBAC**: Service accounts with least-privilege access
- **Real tools**: Kubernetes MCP server for cluster introspection
- **Meaningful goals**: Multi-step monitoring and reporting tasks
- **Tuned intervals**: Balance between freshness and resource usage

KAOS includes a ready-made autonomous monitoring sample. Deploy it with:

```
kaos samples deploy 6-autonomous-monitor
```

Here's what the production sample includes, annotated:

### RBAC: Least-privilege Kubernetes access

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: k8s-monitor-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: k8s-monitor-role
rules:
  # Read-only access to core resources
  - apiGroups: [""]
    resources: ["pods", "services", "events", "namespaces"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list"]
```

### MCP Servers: Kubernetes introspection + report generation

```yaml
# Kubernetes MCP server — queries cluster state
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: monitor-k8s-mcp
spec:
  runtime: kubernetes                    # Built-in Kubernetes runtime
  serviceAccountName: k8s-monitor-sa     # Uses the RBAC service account
  params: |
    allowedNamespaces:
      - kaos-autonomous                  # Scoped to specific namespace
---
# Python MCP server — generates health reports
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: monitor-report-mcp
spec:
  runtime: python-string
  params: |
    from datetime import datetime

    def generate_health_report(pod_data: str) -> str:
        """Generate a formatted cluster health report."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"=== Cluster Health Report ===\nGenerated: {timestamp}\n---\n{pod_data}\n=== End Report ==="

    def check_pod_status(pod_name: str, status: str) -> str:
        """Check whether a pod is healthy or needs attention."""
        healthy = ["Running", "Succeeded", "Completed"]
        icon = "✅" if status in healthy else "❌"
        state = "HEALTHY" if status in healthy else "UNHEALTHY"
        return f"{icon} {pod_name}: {state} ({status})"
```

### Autonomous Agent: Self-looping cluster monitor

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: cluster-monitor
spec:
  modelAPI: monitor-modelapi
  model: "smollm2:135m"
  mcpServers:
    - monitor-k8s-mcp        # Kubernetes introspection tools
    - monitor-report-mcp      # Report generation tools
  config:
    description: "Autonomous cluster monitoring agent"
    instructions: |
      You are a Kubernetes cluster monitoring agent. Your goal is to:
      1. List all pods in the namespace
      2. Check the status of each pod
      3. Generate a health report
    autonomous:
      goal: "Monitor cluster health. List pods, check status, generate report."
      intervalSeconds: 60             # Run every 60 seconds
      maxIterRuntimeSeconds: 120      # Max 2 minutes per iteration
    taskConfig:
      maxIterations: 5                # A2A async tasks: max 5 iterations
      maxRuntimeSeconds: 300          # A2A async tasks: max 5 minutes
      maxToolCalls: 20                # A2A async tasks: max 20 tool calls
    reasoningLoopMaxSteps: 10         # Max model calls per iteration
  agentNetwork:
    expose: true                      # Expose via Gateway API for A2A access
```

Key configuration differences from the demo:
- `intervalSeconds: 60` — production agents don't need sub-second intervals
- `maxIterRuntimeSeconds: 120` — per-iteration timeout prevents runaway execution
- `taskConfig` — separate budgets for A2A async tasks (independent of autonomous loop)
- Real model (`smollm2:135m` via Ollama) instead of mock responses
- Multiple MCP servers working together (Kubernetes + Python report tools)

## Cleanup

```python
subprocess.run(
    ["kubectl", "delete", "namespace", NAMESPACE, "--wait=false"],
    capture_output=True, text=True,
)
print(f"✅ Namespace '{NAMESPACE}' deletion initiated")
```

## Next Steps

- [KAOS Monkey](/examples/kaos-monkey) - Chaos engineering agent with Kubernetes tools
- [Multi-Agent Telemetry](/examples/multi-agent-telemetry) - Multi-agent delegation with OpenTelemetry
- [Agent CRD Reference](/operator/agent-crd) - Full autonomous configuration options
