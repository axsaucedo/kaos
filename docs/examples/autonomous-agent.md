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

KAOS supports two activation modes:
1. **Startup-activated**: Agent begins autonomous execution on pod boot (CRD config)
2. **A2A-triggered**: Send an autonomous task via the A2A protocol at any time

## Prerequisites

- A running Kubernetes cluster with KAOS operator installed
- `kaos` CLI installed and configured
- `kubectl` configured for the cluster

## Setup

```python
import os
os.environ['NAMESPACE'] = 'autonomous-agent-example'
```

```bash
kubectl create namespace $NAMESPACE 2>/dev/null || true
kubectl config set-context --current --namespace=$NAMESPACE
```

## Step 1: Create a ModelAPI

```bash
kaos modelapi deploy auto-api --mode Proxy --wait
```

## Step 2: Create an MCP Server (Echo Tool)

Deploy a simple echo MCP server that the agent can use as a tool:

```bash
export ECHO_FUNC='
def echo(message: str) -> str:
    """Echo the provided message back."""
    return f"Echo: {message}"
'

kaos mcp deploy auto-echo --runtime python-string --params "$ECHO_FUNC" --wait
```

## Step 3: Deploy an Autonomous Agent (Startup-Activated)

Deploy an agent with autonomous mode enabled. Using mock responses for deterministic behavior:

```bash
kaos agent deploy auto-agent \
  --modelapi auto-api \
  --model gpt-4o \
  --mcp auto-echo \
  --instructions "You are a test agent. Use the echo tool when asked." \
  --mock-response '{"tool_calls": [{"id": "call_1", "name": "echo", "arguments": {"message": "hello from autonomous"}}]}' \
  --mock-response "The echo tool confirmed: hello from autonomous. Goal achieved." \
  --autonomous "Use the echo tool to say hello and report the result" \
  --auto-interval 1.0 \
  --wait
```

## Step 4: Verify Autonomous Execution via Memory

The agent runs autonomously on startup. Check that memory recorded the execution:

```bash
sleep 5
kaos agent memory auto-agent
```

Verify the autonomous session was recorded:

```bash
kaos agent memory auto-agent --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
events = data.get('events', [])
assert len(events) >= 2, f'Expected at least 2 events, got {len(events)}'
types = [e['event_type'] for e in events]
assert 'user_message' in types, 'Missing goal user_message'
assert 'agent_response' in types, 'Missing agent_response'
print(f'Autonomous session recorded: {len(events)} events')
for e in events:
    print(f'  [{e[\"event_type\"]}] {str(e.get(\"content\",\"\"))[:80]}')
"
```

## Step 5: Check Agent Status

Verify the agent is healthy and has discovered the echo tool:

```bash
kaos agent status auto-agent
```

Verify capabilities:

```bash
kaos agent status auto-agent --json | python3 -c "
import json, sys
card = json.load(sys.stdin)
assert 'jsonrpc' in card.get('supportedProtocols', []), 'Missing A2A protocol support'
skills = [s['name'] for s in card.get('skills', [])]
assert 'echo' in skills, f'Echo tool not found in skills: {skills}'
print(f'Agent healthy: {len(skills)} tools, A2A enabled')
"
```

## Step 6: A2A Sync Message

Send a synchronous message via the A2A protocol:

```bash
kaos agent a2a send auto-agent --message "Say hello via A2A" --json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
result = data.get('result', {})
state = result.get('status', {}).get('state')
assert state == 'completed', f'Expected completed, got {state}'
history = result.get('history', [])
assert len(history) >= 2, f'Expected at least 2 history entries, got {len(history)}'
agent_msg = [h for h in history if h.get('role') == 'agent']
assert len(agent_msg) > 0, 'No agent response in history'
print(f'A2A sync completed: {state}')
print(f'Agent response: {agent_msg[0][\"parts\"][0][\"text\"][:100]}')
"
```

## Step 7: A2A Autonomous Task

Trigger an autonomous task via the A2A protocol. The task executes asynchronously, so we send it and poll for completion:

```bash
TASK_OUTPUT=$(kaos agent a2a send auto-agent \
  --message "Run autonomous echo check" \
  --mode autonomous \
  --json 2>/dev/null)

TASK_ID=$(echo "$TASK_OUTPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['id'])")
echo "Task ID: $TASK_ID"

sleep 3

kaos agent a2a get auto-agent --task-id "$TASK_ID" --json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
result = data.get('result', {})
state = result.get('status', {}).get('state')
events = result.get('events', [])
event_types = [e['type'] for e in events]
print(f'Task state: {state}')
print(f'Events: {len(events)}')
for e in events:
    print(f'  {e[\"type\"]}: {json.dumps(e.get(\"data\", {}))[:80]}')
assert state in ('completed', 'failed'), f'Task not terminal: {state}'
assert 'task.submitted' in event_types, 'Missing task.submitted event'
"
```

## Step 8: Verify Memory Across Sessions

Multiple sessions should exist (startup + A2A sync + A2A autonomous):

```bash
kaos agent memory auto-agent --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = data.get('total', 0)
assert total >= 4, f'Expected at least 4 events across sessions, got {total}'
print(f'Total memory events across all sessions: {total}')
"
```

## Cleanup

```bash
kubectl delete namespace $NAMESPACE --wait=false
```

## Next Steps

- [Multi-Agent Telemetry](/examples/multi-agent-telemetry) - Multi-agent delegation with OpenTelemetry tracing
- [FastMCP Code Mode](/examples/fastmcp-codemode) - Aggregate MCP servers with Python sandbox
- [Agent CRD Reference](/operator/agent-crd) - Full autonomous configuration options
