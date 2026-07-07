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
      type: remote            # "remote" (bound MemoryStore) or "local" (pod-local)
      memoryStore: shared-memory  # MemoryStore in the same namespace (remote)
      scope: user             # private | user | shared | session
      tools: all              # Expose memory tools: all | read | write
      failureMode: soft       # Override store default: soft | strict
      clientParams:
        tokenBudget: 4096     # Verbatim short-term window cap (tokens)
  
  # Optional: Container overrides (image, env, resources)
  container:
    env:
    - name: AGENT_LOG_LEVEL
      value: "DEBUG"
    - name: CUSTOM_VAR
      value: "custom-value"
    resources:
      requests:
        memory: "256Mi"
        cpu: "200m"
  
  # Optional: Agent-to-Agent networking
  agentNetwork:
    # Create Service for A2A discovery (default: true)
    expose: true           
    access:                # Sub-agents this agent can delegate to
    - worker-1
    - worker-2
  
  # Optional: PodSpec override using strategic merge patch
  podSpec:
    nodeSelector:
      gpu: "true"

status:
  phase: Ready             # Pending, Ready, Failed, Waiting
  ready: true
  endpoint: "http://agent-my-agent.my-namespace.svc.cluster.local:8000"
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

Instructions for the agent. Instructions are re-evaluated on every run and are not retained in the conversation history:

```yaml
config:
  instructions: |
    You are a research assistant.
    When asked to research a topic:
    1. Search for relevant information
    2. Summarize findings concisely
    3. Cite your sources
```

#### config.systemPrompt

Optional system prompt for the agent. Unlike `instructions`, a system prompt is retained in the conversation history. When empty, only `instructions` are applied:

```yaml
config:
  systemPrompt: |
    You are a helpful, concise assistant.
```

#### config.reasoningLoopMaxSteps

Maximum number of reasoning loop iterations:

```yaml
config:
  reasoningLoopMaxSteps: 10  # Default: 5, Range: 1-20
```

The reasoning loop runs tool calls and delegations until the model produces a final response or max steps is reached.

#### config.toolCallMode

Controls how the agent invokes tools:

```yaml
config:
  toolCallMode: auto  # Default: auto, Options: auto, native, string
```

| Mode | Description |
|------|-------------|
| `auto` | Auto-detect via `litellm.supports_function_calling(model)` at startup (default) |
| `native` | Force native OpenAI function calling (`tools` API parameter) |
| `string` | Force text-based JSON tool calling (tool descriptions in system prompt) |

Use `native` or `string` to override auto-detection when the model registry is inaccurate or when you need a specific behavior.

#### config.memory

Memory system configuration. When `type: remote`, the agent binds to a [MemoryStore](./memorystore-crd.md) for semantic, cross-session long-term memory layered on top of the runtime's local short-term window. When `type: local` (or omitted with no `memoryStore`), the agent keeps only a pod-local short-term window.

```yaml
config:
  memory:
    enabled: true               # Enable/disable memory (default: true)
    type: remote                # "remote" or "local" (derived from memoryStore when omitted)
    memoryStore: shared-memory  # MemoryStore in the same namespace (required for remote)
    scope: user                 # private | user | shared | session (default: private)
    tools: all                  # Expose memory tools: all | read | write
    failureMode: soft           # Override store default write/forget mode: soft | strict
    clientParams:
      tokenBudget: 4096         # Verbatim short-term window cap in tokens
      rollingSummary: true      # Maintain a rolling summary of evicted turns
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable memory; when `false`, uses a no-op memory implementation |
| `type` | string | derived | `remote` (bound MemoryStore) or `local` (pod-local short-term). Derived from `memoryStore` presence when omitted |
| `memoryStore` | string | — | Name of a MemoryStore in the same namespace. Required for `remote`; forbidden for `local` |
| `scope` | string | `private` | Whose memory the agent reads/writes: `private`, `user`, `shared`, `session`. `user` and `shared` require a `memoryStore` |
| `tools` | string | — | Explicit memory tools on top of automatic recall/write: `all` (save + search), `read` (search), `write` (save). Requires a `memoryStore` |
| `failureMode` | string | store default | Override the store's write/forget failure mode: `soft` (tolerate) or `strict` (surface errors) |
| `clientParams.tokenBudget` | int | runtime default | Cap on the verbatim short-term window replayed, in tokens |
| `clientParams.rollingSummary` | bool | `true` | Maintain a rolling summary of evicted turns |

**Memory scope (multi-tenancy):**
- `private` (default) — memory is isolated to this single agent; each agent identity owns its own store partition.
- `user` — memory is keyed by the calling principal, so any agent bound to the same store shares that user's memory across sessions. Requires a `memoryStore`.
- `shared` — a single common partition read/written by every agent bound to the store. Requires a `memoryStore`.
- `session` — memory is scoped to an individual conversation/session and not carried across sessions.

**Remote memory:**
- Set `type: remote` and reference a ready MemoryStore via `memoryStore`.
- The operator injects `MEMORY_STORE_ENDPOINT`, `MEMORY_SCOPE`, and a qualified `AGENT_IDENTITY` (`kaos://agent/<namespace>/<name>`) into the agent container.
- Binding is degraded-aware for a running agent: if the store later becomes missing or not-ready it does not block serving — the agent reports a `MemoryDegraded` status condition and falls back to its local short-term window. Initial creation is gated, though: with `waitForDependencies` enabled (default) the agent stays `Waiting` until the bound store is Ready, so it never starts up degraded.

**When to disable memory:**
- Stateless agents that don't need conversation history
- Resource-constrained environments
- High-throughput agents where memory overhead matters

#### config.autonomous (optional)

Autonomous (self-looping) agent execution configuration. When a `goal` is set, the agent runs in an **autonomous loop** on startup — there are no overall iteration or runtime limits. The loop runs forever until the pod is stopped.

```yaml
config:
  autonomous:
    goal: "Monitor system health and report issues"
    intervalSeconds: 5        # Pause between iterations (default: 0)
    maxIterRuntimeSeconds: 60 # Per-iteration wall-clock limit (default: 60, 0 = unlimited)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `goal` | string | | Objective the agent works toward — setting this activates autonomous mode |
| `intervalSeconds` | int32 | `0` | Seconds to pause between iterations (max: 3600) |
| `maxIterRuntimeSeconds` | int32 | `60` | Per-iteration wall-clock limit in seconds (0 = unlimited) |

**Note:** Setting `autonomous.goal` activates autonomous mode. If no goal is set, autonomous mode is simply inactive.

#### config.taskConfig (optional)

Budget limits for **A2A-triggered async tasks** (via `SendMessage` with `mode: "autonomous"`). These are separate from CRD autonomous config.

```yaml
config:
  taskConfig:
    maxIterations: 10       # Max iterations for async tasks (default: 10, 0 = unlimited)
    maxRuntimeSeconds: 300  # Max wall-clock time for async tasks (default: 300, 0 = unlimited)
    maxToolCalls: 50        # Max cumulative tool calls for async tasks (default: 50, 0 = unlimited)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `maxIterations` | int32 | `10` | Max iterations per A2A async task (0 = unlimited) |
| `maxRuntimeSeconds` | int32 | `300` | Max wall-clock seconds per A2A async task (0 = unlimited) |
| `maxToolCalls` | int32 | `50` | Max cumulative tool calls per A2A async task (0 = unlimited) |

**Completion detection for async tasks:** An async task completes when the agent produces a response with no tool calls, or when any budget limit is reached.

### container (optional)

Container overrides for the agent pod.

#### container.env

Additional environment variables:

```yaml
container:
  env:
  - name: AGENT_LOG_LEVEL
    value: "DEBUG"
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: my-secrets
        key: api-key
```

**Note:** The `MODEL_NAME` environment variable is automatically set from `spec.model`.

#### container.resources

Resource requests and limits:

```yaml
container:
  resources:
    requests:
      memory: "256Mi"
      cpu: "200m"
    limits:
      memory: "512Mi"
```

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
- Endpoints: `/health`, `/ready`, `/.well-known/agent.json`, `/v1/chat/completions`

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
