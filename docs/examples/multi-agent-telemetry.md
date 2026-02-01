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

# Multi-Agent System with Telemetry

This example demonstrates building a multi-agent system with delegation between agents. You'll see how a coordinator agent delegates to specialist agents.

## Prerequisites

- KAOS operator installed ([Installation Guide](/getting-started/installation))
- `kaos-cli` installed
- Access to a Kubernetes cluster

## Overview

We'll create:
1. A coordinator agent that delegates to specialists
2. Specialist agents (researcher, analyst) that handle specific tasks
3. Demonstrate agent-to-agent communication via delegation

## Setup

First, let's set up the environment and create a unique namespace:

```python
import os
import subprocess
import time
import json

# Get namespace from environment or create a unique one
namespace = os.environ.get("TEST_NAMESPACE", f"multi-agent-{int(time.time()) % 10000}")
print(f"Using namespace: {namespace}")

# Create namespace
subprocess.run(["kubectl", "create", "namespace", namespace], check=False)
```

## Step 1: Create the ModelAPI

Create a shared ModelAPI for all agents (using mock responses for testing):

```python
# Deploy ModelAPI using kaos CLI
result = subprocess.run(
    ["kaos", "modelapi", "deploy", "team-api", "-n", namespace, "--mode", "Proxy"],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print(f"stderr: {result.stderr}")
```

Wait for ModelAPI to be ready:

```python
# Wait for ModelAPI deployment to be ready
for i in range(60):
    result = subprocess.run(
        ["kubectl", "get", "deployment", "modelapi-team-api", "-n", namespace, 
         "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True
    )
    if result.stdout.strip() == "1":
        print("ModelAPI is ready!")
        break
    time.sleep(2)
else:
    raise TimeoutError("ModelAPI did not become ready")
```

## Step 2: Create the Researcher Agent

Create a specialist agent that handles research tasks:

```python
# Mock response for the researcher
researcher_mock = json.dumps([
    "Here is my research on the topic: AI systems are increasingly being used in enterprise environments. Key trends include automation, decision support, and customer service. Growth is estimated at 40% year-over-year."
])

# Deploy researcher agent
result = subprocess.run([
    "kaos", "agent", "deploy", "researcher",
    "-n", namespace,
    "--modelapi", "team-api",
    "--model", "mock-model",
    "--instructions", "You are a research specialist. You gather and synthesize information on any topic.",
    "--mock-response", researcher_mock,
    "--expose"
], capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print(f"stderr: {result.stderr}")
```

Wait for researcher agent:

```python
# Wait for researcher deployment
for i in range(60):
    result = subprocess.run(
        ["kubectl", "get", "deployment", "agent-researcher", "-n", namespace,
         "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True
    )
    if result.stdout.strip() == "1":
        print("Researcher agent is ready!")
        break
    time.sleep(2)
else:
    raise TimeoutError("Researcher agent did not become ready")
```

## Step 3: Create the Analyst Agent

Create another specialist for data analysis:

```python
# Mock response for the analyst
analyst_mock = json.dumps([
    "Based on my analysis: The data shows 40% year-over-year growth in AI adoption. The highest impact areas are customer service automation (60%), decision support systems (25%), and predictive analytics (15%)."
])

# Deploy analyst agent
result = subprocess.run([
    "kaos", "agent", "deploy", "analyst",
    "-n", namespace,
    "--modelapi", "team-api",
    "--model", "mock-model",
    "--instructions", "You are a data analyst. You analyze information and provide insights with statistics.",
    "--mock-response", analyst_mock,
    "--expose"
], capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print(f"stderr: {result.stderr}")
```

Wait for analyst agent:

```python
# Wait for analyst deployment
for i in range(60):
    result = subprocess.run(
        ["kubectl", "get", "deployment", "agent-analyst", "-n", namespace,
         "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True
    )
    if result.stdout.strip() == "1":
        print("Analyst agent is ready!")
        break
    time.sleep(2)
else:
    raise TimeoutError("Analyst agent did not become ready")
```

## Step 4: Create the Coordinator Agent

Create the coordinator that delegates to specialists:

```python
# Mock responses for the coordinator - it will delegate to both specialists
coordinator_mock = json.dumps([
    'Let me delegate the research portion first.\n\n```delegate\n{"agent": "researcher", "task": "Research AI adoption trends in enterprises"}\n```',
    'Now let me get the analyst\'s perspective.\n\n```delegate\n{"agent": "analyst", "task": "Analyze the growth patterns from the research"}\n```',
    'Based on input from my team:\n\n**Research Summary:** AI is growing in enterprise use with focus on automation and customer service.\n\n**Analysis:** 40% YoY growth, with customer service automation leading at 60%.\n\nThe trend indicates continued expansion in AI-powered automation.'
])

# Deploy coordinator agent with access to other agents
result = subprocess.run([
    "kaos", "agent", "deploy", "coordinator",
    "-n", namespace,
    "--modelapi", "team-api",
    "--model", "mock-model",
    "--instructions", "You are a coordinator. You delegate research to 'researcher' and analysis to 'analyst', then synthesize their responses.",
    "--mock-response", coordinator_mock,
    "--sub-agent", "researcher",
    "--sub-agent", "analyst",
    "--expose"
], capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print(f"stderr: {result.stderr}")
```

Wait for coordinator agent:

```python
# Wait for coordinator deployment
for i in range(60):
    result = subprocess.run(
        ["kubectl", "get", "deployment", "agent-coordinator", "-n", namespace,
         "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True
    )
    if result.stdout.strip() == "1":
        print("Coordinator agent is ready!")
        break
    time.sleep(2)
else:
    raise TimeoutError("Coordinator agent did not become ready")
```

## Step 5: Test the Multi-Agent System

Send a request to the coordinator and watch it delegate:

```python
# Invoke the coordinator
result = subprocess.run([
    "kaos", "agent", "invoke", "coordinator",
    "-n", namespace,
    "--message", "What are the current trends in enterprise AI adoption?"
], capture_output=True, text=True)
print("Coordinator response:")
print(result.stdout)
if result.returncode != 0:
    print(f"stderr: {result.stderr}")
```

## Step 6: Verify the Result

The coordinator should have delegated to both specialists and synthesized their responses:

```python
# Verify the response contains synthesized information
output = result.stdout.lower()
if "40%" in output or "growth" in output or "yoy" in output:
    print("\nSUCCESS: Multi-agent delegation worked correctly!")
    print("The coordinator synthesized responses from researcher and analyst.")
else:
    print("\nResponse may not contain expected synthesis.")
    print("Check the full output above for details.")
```

## How Delegation Works

The coordinator's mock responses include `delegate` blocks:

```
```delegate
{"agent": "researcher", "task": "Research AI trends"}
```
```

When the agent framework sees this, it:
1. Looks up the `researcher` agent in the sub-agents list
2. Sends the task as a message to that agent
3. Waits for the response
4. Includes the response in the conversation context
5. Continues to the next mock response

## Architecture

```mermaid
graph TB
    User[User Request] --> C[Coordinator]
    C --> R[Researcher Agent]
    C --> A[Analyst Agent]
    R --> C
    A --> C
    C --> Response[Synthesized Response]
```

## Enabling Telemetry (Production)

For production use, enable OpenTelemetry on your agents:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: coordinator
spec:
  modelAPI: team-api
  model: gpt-4o
  config:
    telemetry:
      enabled: true
      endpoint: "http://otel-collector.monitoring.svc:4317"
```

This sends traces and metrics to your OTEL collector for observability.

## Cleanup

```python
# Clean up all resources
subprocess.run(["kubectl", "delete", "namespace", namespace, "--ignore-not-found"], 
               capture_output=True)
print(f"Cleaned up namespace: {namespace}")
```

## Next Steps

- [Custom MCP Server](/examples/custom-mcp-server) - Build custom tools
- [KAOS Monkey](/examples/kaos-monkey) - Kubernetes management agent
- [Agent CRD Reference](/operator/agent-crd) - Full configuration options
