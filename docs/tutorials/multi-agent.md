# Tutorial: Multi-Agent Coordination

This tutorial shows how to build a coordinator agent that delegates tasks to specialized worker agents.

## Architecture

```
                    User Request
                         │
                         ▼
                  ┌──────────────┐
                  │ Coordinator  │
                  │    Agent     │
                  └──────┬───────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Worker 1 │  │ Worker 2 │  │ Worker 3 │
    │(Research)│  │(Analysis)│  │ (Writer) │
    └──────────┘  └──────────┘  └──────────┘
```

## Prerequisites

- Agentic operator installed
- kubectl configured
- Ollama running (or in-cluster via Hosted mode)

## Step 1: Create the Namespace and ModelAPI

```yaml
# multi-agent.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: multi-agent-demo

---
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: shared-model
  namespace: multi-agent-demo
spec:
  mode: Hosted
  serverConfig:
    model: "smollm2:135m"
```

## Step 2: Create Worker Agents

Each worker has a specific role:

```yaml
---
# Worker 1: Research Agent
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: researcher
  namespace: multi-agent-demo
spec:
  modelAPI: shared-model
  config:
    description: "Research specialist agent"
    instructions: |
      You are a research specialist.
      When given a topic, provide detailed factual information.
      Focus on accuracy and cite sources when possible.
      Be thorough but concise.
  agentNetwork:
    expose: true  # Required for coordinator to call

---
# Worker 2: Analysis Agent
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: analyst
  namespace: multi-agent-demo
spec:
  modelAPI: shared-model
  config:
    description: "Data analysis specialist agent"
    instructions: |
      You are a data analysis specialist.
      When given data or information, provide insightful analysis.
      Look for patterns, trends, and implications.
      Present findings clearly and logically.
  agentNetwork:
    expose: true

---
# Worker 3: Writing Agent
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: writer
  namespace: multi-agent-demo
spec:
  modelAPI: shared-model
  config:
    description: "Content writing specialist agent"
    instructions: |
      You are a content writing specialist.
      When given information, create well-structured content.
      Focus on clarity, engagement, and proper formatting.
      Adapt your style to the requested format.
  agentNetwork:
    expose: true
```

## Step 3: Create Coordinator Agent

The coordinator can delegate to all workers:

```yaml
---
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: coordinator
  namespace: multi-agent-demo
spec:
  modelAPI: shared-model
  config:
    description: "Coordinator that orchestrates worker agents"
    instructions: |
      You are a coordinator agent managing a team of specialists:
      
      - researcher: For gathering information and facts
      - analyst: For analyzing data and finding insights
      - writer: For creating well-written content
      
      When you receive a complex task:
      1. Break it down into subtasks
      2. Delegate each subtask to the appropriate specialist
      3. Synthesize their responses into a final answer
      
      Use the delegation format to assign tasks.
    agenticLoop:
      maxSteps: 10  # More steps for multi-agent coordination
      enableDelegation: true
  agentNetwork:
    expose: true
    access:
    - researcher
    - analyst
    - writer
```

## Step 4: Deploy Everything

```bash
kubectl apply -f multi-agent.yaml
```

Wait for all resources to be ready:

```bash
kubectl get agent,modelapi -n multi-agent-demo -w
```

Expected output:
```
NAME                                      MODELAPI       READY   PHASE
agent.ethical.institute/analyst           shared-model   true    Ready
agent.ethical.institute/coordinator       shared-model   true    Ready
agent.ethical.institute/researcher        shared-model   true    Ready
agent.ethical.institute/writer            shared-model   true    Ready

NAME                                     MODE     READY   PHASE
modelapi.ethical.institute/shared-model   Hosted   true    Ready
```

## Step 5: Test the Coordinator

Port-forward to the coordinator:

```bash
kubectl port-forward -n multi-agent-demo svc/coordinator 8000:80
```

Send a complex request that requires multiple specialists:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "coordinator",
    "messages": [{
      "role": "user",
      "content": "Research quantum computing, analyze its potential impact on cryptography, and write a brief executive summary."
    }]
  }'
```

The coordinator should:
1. Delegate research to `researcher`
2. Delegate analysis to `analyst`
3. Delegate writing to `writer`
4. Combine responses into final answer

## Step 6: Verify Delegation via Memory

Check the coordinator's memory to see delegation events:

```bash
curl http://localhost:8000/memory/events | jq
```

You should see events like:
```json
{
  "events": [
    {"event_type": "user_message", "content": "Research quantum..."},
    {"event_type": "delegation_request", "content": {"agent": "researcher", "task": "..."}},
    {"event_type": "delegation_response", "content": {"agent": "researcher", "response": "..."}},
    {"event_type": "delegation_request", "content": {"agent": "analyst", "task": "..."}},
    {"event_type": "delegation_response", "content": {"agent": "analyst", "response": "..."}},
    {"event_type": "agent_response", "content": "Final synthesized answer..."}
  ]
}
```

## Deterministic Testing with Mock Responses

For testing, use `DEBUG_MOCK_RESPONSES` to control model responses:

```yaml
# In the coordinator Agent spec
spec:
  config:
    env:
    - name: DEBUG_MOCK_RESPONSES
      value: '["```delegate\n{\"agent\": \"researcher\", \"task\": \"Research AI developments\"}\n```", "Based on the research: AI is advancing rapidly."]'
```

This forces the coordinator to delegate to the researcher, enabling deterministic E2E tests.

## Adding Tools to Workers

Enhance workers with MCP tools:

```yaml
---
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: search-tools
  namespace: multi-agent-demo
spec:
  type: python-runtime
  config:
    toolsString: |
      def search(query: str) -> str:
          """Search for information."""
          return f"Search results for: {query}"

---
# Update researcher to use tools
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: researcher
  namespace: multi-agent-demo
spec:
  modelAPI: shared-model
  mcpServers:
  - search-tools
  config:
    description: "Research specialist with search capability"
    instructions: |
      You are a research specialist with search tools.
      Use the search tool to find information before responding.
    agenticLoop:
      enableTools: true
  agentNetwork:
    expose: true
```

## Cleanup

```bash
kubectl delete namespace multi-agent-demo
```

## Best Practices

1. **Clear Role Definitions**: Give each worker a distinct specialty
2. **Explicit Instructions**: Tell coordinator when to use each worker
3. **Appropriate max_steps**: Multi-agent tasks need more iterations
4. **Monitor Memory**: Use `/memory/events` to debug delegation flows
5. **Error Handling**: Workers should handle errors gracefully
6. **Resource Limits**: Set appropriate limits for each agent
