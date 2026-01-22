# Agent CRD

The Agent custom resource defines an AI agent deployment on Kubernetes.

## Full Specification

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
  namespace: my-namespace
spec:
  # Required: Reference to ModelAPI for LLM access
  modelAPI: my-modelapi
  
  # Required: Model to use (must be supported by the referenced ModelAPI)
  model: "openai/gpt-4o"
  
  # Optional: List of MCPServer references for tool access
  mcpServers:
  - echo-tools
  - calculator-tools
  
  # Optional: Wait for dependencies to be ready (default: true)
  waitForDependencies: true
  
  # Optional: Agent configuration
  config:
    # Human-readable description for humans and other agents for a2a delegation
    description: "My helpful agent that performs tasks X/Y"
    
    # System prompt instructions
    instructions: |
      You are a helpful assistant.
      Be concise and accurate.
    
    # Max reasoning loop iterations (1-20, default: 5)
    reasoningLoopMaxSteps: 5
    
    # Memory system configuration
    memory:
      enabled: true           # Enable/disable memory (default: true)
      type: local             # Memory type (only "local" supported)
      contextLimit: 6         # Messages for delegation context
      maxSessions: 1000       # Max sessions to keep
      maxSessionEvents: 500   # Max events per session
    
    # Additional environment variables
    env:
    - name: CUSTOM_VAR
      value: "custom-value"
  
  # Optional: Agent-to-Agent networking
  agentNetwork:
    # Create Service for A2A discovery (default: true)
    expose: true           
    access:                # Sub-agents this agent can delegate to
    - worker-1
    - worker-2
  
  # Optional: PodSpec override using strategic merge patch
  podSpec:
    containers:
    - name: agent
      resources:
        requests:
          memory: "256Mi"
          cpu: "200m"
        limits:
          memory: "512Mi"
          cpu: "1000m"

status:
  phase: Ready             # Pending, Ready, Failed, Waiting
  ready: true
  endpoint: "http://agent-my-agent.my-namespace.svc.cluster.local:8000"
  model: "openai/gpt-4o"   # Model being used
  linkedResources:
    modelAPI: my-modelapi
  message: "Deployment ready replicas: 1/1"
  deployment:
    replicas: 1
    readyReplicas: 1
    availableReplicas: 1
    updatedReplicas: 1
    conditions:
    - type: Available
      status: "True"
    - type: Progressing
      status: "True"
```

## Spec Fields

### modelAPI (required)

Reference to a ModelAPI resource in the same namespace.

```yaml
spec:
  modelAPI: my-modelapi
```

The agent waits for the ModelAPI to become Ready before starting (see `waitForDependencies`).

### model (required)

The LLM model to use. Must be supported by the referenced ModelAPI.

```yaml
spec:
  modelAPI: my-modelapi
  model: "openai/gpt-4o"
```

**Validation:**
- The agent controller validates that this model is supported by the ModelAPI
- Supports exact matches: `openai/gpt-4o` matches `openai/gpt-4o`
- Supports provider wildcards: `openai/gpt-4o` matches `openai/*`
- Supports full wildcards: any model matches `*`

If the model is not supported, the agent status will show `Failed` with an error message.

**Note:** Model validation happens at agent creation/update time. If a ModelAPI's supported models change after an agent is created, the agent continues running but may fail at runtime if the model is no longer available.

### mcpServers (optional)

List of MCPServer resource names in the same namespace.

```yaml
spec:
  mcpServers:
  - echo-tools
  - calculator-tools
```

All referenced MCPServers must be Ready for the agent to start (see `waitForDependencies`).

### waitForDependencies (optional)

Controls whether the agent waits for ModelAPI and MCPServers to be ready before creating the deployment.

```yaml
spec:
  waitForDependencies: true  # Default: true
```

| Value | Behavior |
|-------|----------|
| `true` (default) | Agent deployment is created only after ModelAPI and all MCPServers are Ready |
| `false` | Agent deployment is created immediately; agent handles unavailable dependencies gracefully at runtime |

Setting to `false` is useful when:
- Deploying agents in any order without worrying about startup sequence
- Using the Python agent's graceful degradation for unavailable sub-agents/tools

### config (optional)

Agent-specific configuration.

#### config.description

Human-readable description shown in agent card:

```yaml
config:
  description: "A research assistant agent"
```

#### config.instructions

System prompt for the agent:

```yaml
config:
  instructions: |
    You are a research assistant.
    When asked to research a topic:
    1. Search for relevant information
    2. Summarize findings concisely
    3. Cite your sources
```

#### config.reasoningLoopMaxSteps

Maximum number of reasoning loop iterations:

```yaml
config:
  reasoningLoopMaxSteps: 10  # Default: 5, Range: 1-20
```

The reasoning loop runs tool calls and delegations until the model produces a final response or max steps is reached.

#### config.memory

Memory system configuration:

```yaml
config:
  memory:
    enabled: true           # Enable/disable memory (default: true)
    type: local             # Memory type (default: local, only option)
    contextLimit: 6         # Messages for delegation context (default: 6)
    maxSessions: 1000       # Max sessions to keep (default: 1000)
    maxSessionEvents: 500   # Max events per session (default: 500)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable memory; when `false`, uses NullMemory (no-op) |
| `type` | string | `local` | Memory implementation type (only `local` supported) |
| `contextLimit` | int | `6` | Messages to include when delegating to sub-agents |
| `maxSessions` | int | `1000` | Maximum sessions before oldest are evicted |
| `maxSessionEvents` | int | `500` | Maximum events per session before eviction |

**When to disable memory:**
- Stateless agents that don't need conversation history
- Resource-constrained environments
- High-throughput agents where memory overhead matters

#### config.env

Additional environment variables:

```yaml
config:
  env:
  - name: CUSTOM_VAR
    value: "my-value"
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: my-secrets
        key: api-key
```

**Note:** The `MODEL_NAME` environment variable is automatically set from `spec.model`.

### agentNetwork (optional)

Agent-to-Agent networking configuration.

#### agentNetwork.expose

Create a Kubernetes Service for this agent (default: true):

```yaml
agentNetwork:
  expose: true
```

When `true`, creates a Service that exposes:
- Port 8000
- Endpoints: `/health`, `/ready`, `/.well-known/agent`, `/agent/invoke`, `/v1/chat/completions`

#### agentNetwork.access

List of agent names this agent can delegate to:

```yaml
agentNetwork:
  access:
  - worker-1
  - worker-2
```

The operator automatically:
1. Finds the referenced Agent resources
2. Sets `PEER_AGENTS=worker-1,worker-2`
3. Sets `PEER_AGENT_WORKER_1_CARD_URL=http://agent-worker-1...`
4. Sets `PEER_AGENT_WORKER_2_CARD_URL=http://agent-worker-2...`

### podSpec (optional)

Override the generated pod spec using Kubernetes strategic merge patch.

```yaml
spec:
  podSpec:
    containers:
    - name: agent  # Must match the generated container name
      resources:
        requests:
          memory: "256Mi"
          cpu: "100m"
        limits:
          memory: "512Mi"
    tolerations:
    - key: "gpu"
      operator: "Exists"
    nodeSelector:
      accelerator: "nvidia"
```

**Strategic Merge Behavior:**
- Container fields are merged by name (container `name` must be `agent`)
- New fields are added, existing fields are overwritten
- Useful for: resources, tolerations, nodeSelector, volumes, securityContext

**Note:** Replicas cannot be set via podSpec; it's a deployment-level setting (currently fixed at 1).

### gatewayRoute (optional)

Configure Gateway API routing, including request timeout:

```yaml
spec:
  gatewayRoute:
    # Request timeout for the HTTPRoute (Gateway API Duration format)
    # Default: "120s" for Agent (to allow multi-step reasoning)
    # Set to "0s" to use Gateway's default timeout
    timeout: "120s"
```

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed, Waiting |
| `ready` | bool | Whether agent is ready to serve |
| `endpoint` | string | Service URL for A2A communication |
| `model` | string | Model being used by this agent |
| `linkedResources` | map | References to dependencies |
| `message` | string | Additional status information |
| `deployment` | object | Deployment status for rolling update visibility |

### deployment (status)

Mirrors key status fields from the underlying Kubernetes Deployment:

| Field | Type | Description |
|-------|------|-------------|
| `replicas` | int32 | Total number of non-terminated pods |
| `readyReplicas` | int32 | Number of pods with Ready condition |
| `availableReplicas` | int32 | Number of available pods (ready for minReadySeconds) |
| `updatedReplicas` | int32 | Number of pods with desired template (rolling update progress) |
| `conditions` | array | Deployment conditions (Available, Progressing, ReplicaFailure) |

Example status during a rolling update:

```yaml
status:
  phase: Pending
  ready: false
  model: "openai/gpt-4o"
  deployment:
    replicas: 2
    readyReplicas: 1
    availableReplicas: 1
    updatedReplicas: 1
    conditions:
    - type: Progressing
      status: "True"
      reason: ReplicaSetUpdated
      message: "ReplicaSet 'agent-my-agent-xyz' is progressing"
    - type: Available
      status: "True"
      reason: MinimumReplicasAvailable
```

## Examples

### Simple Agent

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: simple-agent
spec:
  modelAPI: ollama
  model: "ollama/smollm2:135m"
  config:
    description: "A simple chat agent"
    instructions: "You are a helpful assistant."
```

### Agent with Tools

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: tool-agent
spec:
  modelAPI: ollama
  model: "ollama/llama3"
  mcpServers:
  - calculator
  - web-search
  config:
    description: "An agent with tools"
    instructions: |
      You have access to a calculator and web search.
      Use them when appropriate.
    reasoningLoopMaxSteps: 10
```

### Coordinator with Workers

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: coordinator
spec:
  modelAPI: openai
  model: "openai/gpt-4o"
  config:
    description: "Coordinator agent"
    instructions: |
      You coordinate worker agents.
      Delegate research to researcher.
      Delegate analysis to analyst.
    reasoningLoopMaxSteps: 10
  agentNetwork:
    access:
    - researcher
    - analyst
```

### Agent with Resource Limits

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: resource-agent
spec:
  modelAPI: ollama
  model: "ollama/llama3"
  config:
    description: "Agent with custom resources"
  podSpec:
    containers:
    - name: agent
      resources:
        requests:
          memory: "512Mi"
          cpu: "500m"
        limits:
          memory: "2Gi"
          cpu: "2000m"
```

### Agent without Waiting for Dependencies

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: eager-agent
spec:
  modelAPI: ollama
  model: "ollama/smollm2:135m"
  waitForDependencies: false  # Start immediately
  config:
    description: "Agent that handles unavailable dependencies gracefully"
```

## Troubleshooting

### Agent Stuck in Pending

```bash
kubectl describe agent my-agent -n my-namespace
```

Common causes:
- ModelAPI not Ready
- MCPServer not Ready

### Agent Stuck in Waiting

The agent is waiting for dependencies. Check:

```bash
kubectl get modelapi -n my-namespace
kubectl get mcpserver -n my-namespace
```

Set `waitForDependencies: false` to allow the agent to start without waiting.

### Agent in Failed State

Check status message:

```bash
kubectl get agent my-agent -o jsonpath='{.status.message}'
```

Common causes:
- Model not supported by ModelAPI (e.g., agent uses `openai/gpt-4o` but ModelAPI only supports `anthropic/*`)
- Invalid configuration

### Pod Errors

Check pod logs:

```bash
kubectl logs -l agent=my-agent -n my-namespace
```

Common causes:
- Invalid MODEL_API_URL
- Model not available at backend
- Image pull errors

### Sub-Agent Delegation Failing

Verify peer agent is accessible:

```bash
# Check if service exists
kubectl get svc agent-worker-1 -n my-namespace

# Check agent card endpoint
kubectl exec -it deploy/agent-coordinator -n my-namespace -- \\
  curl http://agent-worker-1:8000/.well-known/agent
```
