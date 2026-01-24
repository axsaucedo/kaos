# KAOS (K8s Agent Orchestration System) - Project Documentation

## Commit Guidelines
Use conventional commits with brief, functional descriptions:
- `feat(scope): add feature` - New functionality
- `fix(scope): fix issue` - Bug fixes
- `refactor(scope): change implementation` - Code changes without new features
- `test(scope): update tests` - Test changes
- `docs: update documentation` - Documentation only

Keep commits atomic and easy to review. Group related changes logically.

## Overview
Custom Agent Runtime framework (replacing Google ADK) for Kubernetes-native AI agents.

## Project Structure
```
python/                    # Agent runtime framework
├── agent/                 # Agent implementation
│   ├── client.py          # Agent, RemoteAgent, AgentCard, max_steps parameter classes
│   ├── server.py          # AgentServer with health/ready probes, A2A endpoints
│   └── memory.py          # LocalMemory for session/event management
├── mcptools/              # MCP (Model Context Protocol) tools
│   ├── server.py          # MCPServer wrapping FastMCP with health/ready probes
│   └── client.py          # MCPClient for tool discovery and invocation
├── modelapi/              # Model API client
│   └── client.py          # ModelAPI for OpenAI-compatible servers (supports mock_response)
├── Makefile               # Python build and test targets
├── Dockerfile             # Agent container image
└── tests/                 # Test suite (36 tests)

operator/                  # Kubernetes operator (Go/kubebuilder)
├── api/v1alpha1/          # CRD type definitions
│   ├── agent_types.go     # Agent CRD with max_steps parameter
│   ├── mcpserver_types.go # MCPServer CRD
│   └── modelapi_types.go  # ModelAPI CRD
├── controllers/           # Reconcilers
│   ├── agent_controller.go
│   ├── mcpserver_controller.go
│   ├── modelapi_controller.go
│   └── integration/       # Go integration tests (8 tests with envtest)
├── config/                # Kubernetes manifests
│   ├── crd/bases/         # CRD YAML files
│   └── samples/           # Example resources
├── hack/                  # CI/CD scripts
│   ├── run-e2e-tests.sh   # Main E2E test runner
│   ├── build-push-images.sh
│   ├── kind-with-registry.sh
│   ├── install-gateway.sh
│   └── install-metallb.sh
├── Makefile               # Operator build, test, and E2E targets
└── tests/e2e/             # E2E tests (14 tests)

.github/workflows/         # GitHub Actions
├── docker-push.yaml       # Build and push images on main
├── e2e-tests.yaml         # E2E tests in KIND
├── go-tests.yaml          # Go unit tests
└── python-tests.yaml      # Python unit tests
```

## Key Principles
- **KEEP IT SIMPLE** - Avoid over-engineering
- Python commands: `cd python && source .venv/bin/activate && <command>`
- Operator E2E: `cd operator && make kind-create && make kind-e2e-run-tests`
- Tests AND linting are the success criteria for development
- **Documentation**: When making changes, update both `CLAUDE.md` AND `docs/` directory

## Running Tests and Linting

**IMPORTANT**: CI runs both tests AND linting. Always run both before committing.

### Python Tests and Linting
```bash
cd python
source .venv/bin/activate

# Run tests (39 tests)
python -m pytest tests/ -v

# Run linting (required for CI to pass)
make lint  # Runs: black --check . && uvx ty check

# Format code if black fails
make format
```

### Go Unit Tests
```bash
cd operator
make test-unit  # Runs envtest-based integration tests
```

### Kubernetes E2E Tests (Docker Desktop)

E2E tests use Gateway API for routing and Helm for operator installation.

```bash
# Prerequisites: Gateway API CRDs and controller installed
# kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.1/standard-install.yaml
# helm install envoy-gateway oci://docker.io/envoyproxy/gateway-helm --version v1.4.6 --namespace envoy-gateway-system --create-namespace --skip-crds

cd operator
make e2e-test      # Parallel execution
make e2e-test-seq  # Sequential execution with debug output
make e2e-clean     # Clean up test resources
```

### KIND E2E Tests (Isolated Cluster)

Run E2E tests in an isolated KIND cluster with local registry:

```bash
cd operator

# Create KIND cluster with Gateway API and MetalLB
make kind-create

# Run full E2E (builds images, installs operator, runs tests):
make kind-e2e-run-tests

# Individual steps (for debugging):
make kind-load-images      # Build and load images into KIND
make kind-e2e-install-kaos # Generate Helm values and install operator
make e2e-test              # Run E2E tests (parallel)

# Delete KIND cluster
make kind-delete
```

The `kind-e2e-run-tests` target runs: `kind-load-images` → `kind-e2e-install-kaos` → `e2e-test`
This is the same setup used in GitHub Actions CI.

## Docker Images

Official images are published to Docker Hub under `axsauze/`:

| Image | Description |
|-------|-------------|
| `axsauze/kaos-operator:latest` | Kubernetes operator controller |
| `axsauze/kaos-agent:latest` | Agent runtime (also used for MCP servers) |

Images are automatically built and pushed on merge to main via `.github/workflows/docker-push.yaml`.

### Helm Chart Default Images
The Helm chart (`operator/chart/values.yaml`) uses these defaults:
```yaml
defaultImages:
  agentRuntime: "axsauze/kaos-agent:latest"
  mcpServer: "axsauze/kaos-agent:latest"
  litellm: "ghcr.io/berriai/litellm:main-latest"
  ollama: "alpine/ollama:latest"
```

## Dependencies
- Ollama running locally with `smollm2:135m` model (for local host-Ollama tests)
- Docker Desktop with Kubernetes enabled
- `docker-desktop` kubectl context
- Gateway API CRDs installed
- Envoy Gateway (or other Gateway controller) installed

---

## Python Agent Framework

### Agent (agent/client.py)
- `Agent` - Main agent class with agentic loop, message processing, memory, MCP tools, sub-agents
- `RemoteAgent` - Remote agent client with `_init()` for discovery and `process_message()` for delegation
- `MCPClient` - MCP tool client with `_init()` for tool discovery and `call_tool()` for execution
- `AgentCard` - A2A discovery card with capabilities and skills
- `max_steps parameter` - Configuration for agentic reasoning loop (max_steps only)

### Graceful Degradation Pattern
Both `RemoteAgent` and `MCPClient` use the same pattern:
- `_active` flag tracks if the client is initialized and working
- `_init()` attempts discovery/initialization, returns `True` on success
- On failure, `_active=False` and methods raise `RuntimeError` with exception type and message
- Calling methods auto-reinitialize if `_active=False`, enabling recovery

```python
# RemoteAgent example
if not self._active:
    if not await self._init():
        raise RuntimeError(f"Agent {self.name} unavailable at {self.card_url}")
```

### Multi-Agent Ordering
When agents start in different order (e.g., coordinator before workers):
- **Timeout**: 5 seconds for both discovery and invocation
- **Graceful degradation**: Unavailable agents shown as "(unavailable)" in system prompt
- **Auto-retry**: Re-inits on each request, allowing recovery when available
- **Informative errors**: `RuntimeError` includes exception type (e.g., `ConnectError: ...`)

### Agentic Loop
The agent implements a reasoning loop that:
1. Builds system prompt with available tools and agents
2. Sends message to model
3. Parses response for tool calls or delegations
4. Executes tool/delegation and loops until final response or max_steps

**Tool Call Format** (in model response):
```
```tool_call
{"tool": "tool_name", "arguments": {"arg1": "value"}}
```
```

**Delegation Format** (in model response):
```
```delegate
{"agent": "agent_name", "task": "task description"}
```
```

### AgentServer (agent/server.py)
- `/health` and `/ready` - Kubernetes probes
- `/.well-known/agent` - A2A agent card endpoint
- `/v1/chat/completions` - OpenAI-compatible endpoint (primary API)
- `/memory/events` and `/memory/sessions` - Debug endpoints (when enabled)

### ModelAPI (modelapi/client.py)
- `process_message(messages)` - Non-streaming completion, returns str
- `process_message_stream(messages)` - Streaming completion, yields str chunks
- Supports `DEBUG_MOCK_RESPONSES` env var for deterministic testing

### Deterministic Testing with DEBUG_MOCK_RESPONSES
Set `DEBUG_MOCK_RESPONSES` env var on ModelAPI to bypass model API and use mock responses:
```bash
# Single response
DEBUG_MOCK_RESPONSES='["Hello from mock"]'

# Multi-step agentic loop (tool call then final response)
DEBUG_MOCK_RESPONSES='["```tool_call\n{\"tool\": \"echo\", \"arguments\": {\"msg\": \"hi\"}}\n```", "Tool returned: hi"]'

# Delegation flow (coordinator delegates to worker)
DEBUG_MOCK_RESPONSES='["```delegate\n{\"agent\": \"worker-1\", \"task\": \"Process data\"}\n```", "Worker completed the task."]'
```

This enables deterministic E2E tests for tool calling and delegation flows.

### Internal Delegation Protocol
When an agent delegates to a sub-agent:
1. The delegating agent calls `RemoteAgent.invoke()` with messages array
2. The last message has `role: "task-delegation"` with the delegated task
3. The sub-agent logs this as `task_delegation_received` in memory
4. The `task-delegation` role is converted to `user` role for the model

### AgentServerSettings Environment Variables
| Variable | Description |
|----------|-------------|
| `AGENT_NAME` | Agent name (required) |
| `AGENT_DESCRIPTION` | Agent description |
| `AGENT_INSTRUCTIONS` | System prompt |
| `MODEL_API_URL` | LLM API base URL (required) |
| `MODEL_NAME` | Model name (required) |
| `AGENT_SUB_AGENTS` | Direct format: `"name:url,name:url"` |
| `PEER_AGENTS` | K8s format: `"worker-1,worker-2"` |
| `PEER_AGENT_<NAME>_CARD_URL` | K8s format: individual URLs |
| `AGENT_ACCESS_LOG` | Enable uvicorn access logs (default: false) |
| `AGENTIC_LOOP_MAX_STEPS` | Max reasoning steps (default: 5) |
| `MEMORY_ENABLED` | Enable/disable memory (default: true) |
| `MEMORY_TYPE` | Memory type, only "local" supported (default: local) |
| `MEMORY_CONTEXT_LIMIT` | Messages for delegation context (default: 6) |
| `MEMORY_MAX_SESSIONS` | Max sessions to keep (default: 1000) |
| `MEMORY_MAX_SESSION_EVENTS` | Max events per session (default: 500) |
| `DEBUG_MOCK_RESPONSES` | JSON array of mock responses for testing |

### MCPServer Environment Variables
| Variable | Description |
|----------|-------------|
| `MCP_HOST` | Host to bind to (default: `0.0.0.0`) |
| `MCP_PORT` | Port to listen on (default: `8000`) |
| `MCP_TOOLS_STRING` | Python code defining tools |
| `MCP_LOG_LEVEL` | Log level (default: `INFO`) |
| `MCP_ACCESS_LOG` | Enable uvicorn access logs (default: false) |

---

## Kubernetes Operator

### CRDs
- `Agent` - Deploys agent pods with model API and MCP server connections
- `MCPServer` - Deploys MCP tool servers
- `ModelAPI` - Deploys LiteLLM proxy to LLM backends

### Agent CRD Example
```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: coordinator
spec:
  modelAPI: ollama-proxy
  model: "ollama/smollm2:135m"  # Required: must be supported by ModelAPI
  mcpServers: []
  waitForDependencies: true  # Default: wait for ModelAPI/MCPServers to be ready
  config:
    description: "Coordinator agent"
    instructions: "You manage worker agents."
    reasoningLoopMaxSteps: 5  # Max reasoning loop iterations
    memory:
      enabled: true           # Enable/disable memory (default: true)
      type: local             # Memory type (only local supported)
      contextLimit: 6         # Messages for delegation context
      maxSessions: 1000       # Max sessions to keep
      maxSessionEvents: 500   # Max events per session
  agentNetwork:
    # expose defaults to true - creates Service for A2A
    access:
    - worker-1  # Sub-agents this agent can delegate to
    - worker-2
  # Use podSpec for resource overrides via strategic merge patch
  podSpec:
    containers:
    - name: agent
      resources:
        requests:
          memory: "256Mi"
          cpu: "100m"
        limits:
          memory: "512Mi"
```

### PodSpec Strategic Merge
All CRDs (Agent, MCPServer, ModelAPI) support `podSpec` for customizing the generated pod:
- Uses Kubernetes strategic merge patch semantics
- Container `name` must match the generated container name (`agent`, `mcp-server`, `model-api`)
- Common use cases: resource requests/limits, volumes, tolerations, nodeSelector
- Does NOT override replicas (deployment-level setting)

### waitForDependencies
Controls agent startup behavior:
- `true` (default): Agent waits for ModelAPI and MCPServers to be Ready before creating deployment
- `false`: Agent deployment created immediately; handles unavailable dependencies at runtime

### Gateway Route Configuration
All CRDs (Agent, MCPServer, ModelAPI) support `gatewayRoute` for customizing HTTPRoute behavior:

```yaml
spec:
  gatewayRoute:
    timeout: "120s"  # Request timeout for this resource's HTTPRoute
```

**Default Timeouts** (configured via Helm chart values or operator env vars):
- Agent: 120s (multi-step reasoning)
- ModelAPI: 120s (LLM inference can take time)
- MCPServer: 30s (tool calls are typically fast)

**Operator Configuration Environment Variables:**
All operator configuration is managed via the `kaos-operator-config` ConfigMap, which sets the following env vars:

| Variable | Description | Default |
|----------|-------------|---------|
| `DEFAULT_AGENT_IMAGE` | Default agent container image | `axsauze/kaos-agent:latest` |
| `DEFAULT_MCP_SERVER_IMAGE` | Default MCP server image | `axsauze/kaos-agent:latest` |
| `DEFAULT_LITELLM_IMAGE` | Default LiteLLM proxy image | `ghcr.io/berriai/litellm:main-latest` |
| `DEFAULT_OLLAMA_IMAGE` | Default Ollama image | `alpine/ollama:latest` |
| `GATEWAY_API_ENABLED` | Enable Gateway API integration | `false` |
| `GATEWAY_NAME` | Name of the Gateway resource | `kaos-gateway` |
| `GATEWAY_NAMESPACE` | Namespace of the Gateway | Release namespace |
| `GATEWAY_DEFAULT_AGENT_TIMEOUT` | Default timeout for Agent HTTPRoutes | `120s` |
| `GATEWAY_DEFAULT_MODELAPI_TIMEOUT` | Default timeout for ModelAPI HTTPRoutes | `120s` |
| `GATEWAY_DEFAULT_MCP_TIMEOUT` | Default timeout for MCPServer HTTPRoutes | `30s` |

These can be set via Helm values:
```yaml
defaultImages:
  agentRuntime: "axsauze/kaos-agent:latest"
  mcpServer: "axsauze/kaos-agent:latest"
  litellm: "ghcr.io/berriai/litellm:main-latest"
  ollama: "alpine/ollama:latest"
gateway:
  defaultTimeouts:
    agent: "120s"
    modelAPI: "120s"
    mcp: "30s"
gatewayAPI:
  enabled: true
  gatewayName: "kaos-gateway"
```

### Controller Environment Variables
The operator sets these env vars on agent pods:
- `AGENT_NAME`, `AGENT_DESCRIPTION`, `AGENT_INSTRUCTIONS`
- `MODEL_API_URL` - From ModelAPI.Status.Endpoint
- `MODEL_NAME` - From Agent.Spec.Model (required)
- `AGENT_DEBUG_MEMORY_ENDPOINTS=true` - Enabled by default
- `PEER_AGENTS` - Comma-separated sub-agent names from `agentNetwork.access`
- `PEER_AGENT_<NAME>_CARD_URL` - Each sub-agent's service URL
- `AGENTIC_LOOP_MAX_STEPS` - From config.reasoningLoopMaxSteps

### Agent Model Validation
The agent controller validates `spec.model` against the ModelAPI's `status.supportedModels`:
- Exact match: `openai/gpt-4o` matches `openai/gpt-4o`
- Provider wildcard: `openai/gpt-4o` matches `openai/*`
- Full wildcard: any model matches `*`

If validation fails, the agent status shows `Failed` with an error message.

**Design Decision:** Model validation only happens at agent creation/update. If a ModelAPI's models change, existing agents are not automatically invalidated - they may fail at runtime.

### LiteLLM Configuration Architecture
The ModelAPI controller generates LiteLLM config based on `proxyConfig.models`:

1. **Explicit Models** - When `proxyConfig.models` contains specific models:
   - Generates config with each model in `model_list`
   - Uses `PROXY_API_KEY` and `PROXY_API_BASE` env vars if apiKey/apiBase provided

2. **Wildcard Mode** - When `proxyConfig.models: ["*"]`:
   - Generates wildcard config that proxies any model to backend
   - Best for development and flexible setups

3. **Config File Mode (Advanced)** - When `proxyConfig.configYaml.fromString` is provided:
   - Uses user-provided config directly
   - Validates that `model_name` entries match `models` list
   - Best for multi-model routing, load balancing, etc.

**WARNING: Don't add `completion_model` to general_settings - it causes periodic backend calls every 5 seconds.**

### ModelAPI Modes
- **Proxy** - LiteLLM proxy to external backends (Ollama, OpenAI, etc.). Service port: 8000
- **Hosted** - Run Ollama in-cluster with model specified in hostedConfig. Service port: 11434

### ModelAPI Hosted Mode (In-Cluster Ollama)
When using `mode: Hosted`, the operator deploys Ollama in-cluster and automatically pulls the specified model:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: my-ollama
spec:
  mode: Hosted
  hostedConfig:
    model: "smollm2:135m"  # Model is auto-pulled on startup
    env:
    - name: OLLAMA_DEBUG
      value: "false"
```

**How it works:**
- An init container starts Ollama, pulls the model, then exits
- The model is stored in an emptyDir volume shared with the main container
- The main Ollama container starts with the model already available
- First pod startup may take 1-2 minutes depending on model size

**ServerConfig Fields:**
- `model` - Ollama model to pull (e.g., `smollm2:135m`, `llama2`, `mistral`)
- `env` - Environment variables for the Ollama container
- `resources` - Resource requests/limits for the container

### ModelAPI ProxyConfig
The ProxyConfig requires a `models` list:

**Basic Configuration:**
```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: my-proxy
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "openai/gpt-4o"
    - "openai/gpt-4o-mini"
    apiBase: "https://api.openai.com"
    apiKey:
      valueFrom:
        secretKeyRef:
          name: openai-secrets
          key: api-key
```

**Wildcard Mode (Development):**
```yaml
spec:
  mode: Proxy
  proxyConfig:
    models: ["*"]  # Allow any model
    apiBase: "http://host.docker.internal:11434"
```

**Provider Wildcards:**
```yaml
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "openai/*"    # Any OpenAI model
    - "anthropic/*" # Any Anthropic model
```

For advanced multi-model routing, provide a full LiteLLM config:
```yaml
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "gpt-4"
    - "claude-3"
    configYaml:
      fromString: |
        model_list:
          - model_name: "gpt-4"
            litellm_params:
              model: "openai/gpt-4"
              api_key: "os.environ/PROXY_API_KEY"
          - model_name: "claude-3"
            litellm_params:
              model: "claude-3-sonnet-20240229"
              api_key: "os.environ/ANTHROPIC_API_KEY"
```

**ProxyConfig Fields:**
- `models` (required) - List of supported models (used for agent validation)
- `apiBase` - Backend LLM API URL, set as `PROXY_API_BASE` env var
- `apiKey` - API key, set as `PROXY_API_KEY` env var (value or valueFrom)
- `configYaml` - Full LiteLLM config YAML (optional, for advanced use)
- `env` - Additional environment variables for the container

### RBAC - CRITICAL DO NOT REMOVE
The operator requires these RBAC permissions in `operator/config/rbac/role.yaml`:
- **leases** (coordination.k8s.io) - Required for leader election
- **events** ("") - Required for leader election events
- **configmaps, services** - Required for reconciling resources
- **deployments** (apps) - Required for creating pods

**IMPORTANT: The `role.yaml` file is auto-generated by `controller-gen` from `// +kubebuilder:rbac:` annotations in Go files.**
- Leases and events RBAC are defined in `operator/main.go` (NOT controller files)
- Running `make manifests` regenerates `role.yaml` from these annotations
- **Never manually edit role.yaml** - changes will be overwritten
- To add new RBAC rules, add `// +kubebuilder:rbac:` annotations to the appropriate Go file

**WARNING: Never remove the leases or events annotations from main.go - they are essential for operator leader election.**

### Building and Testing

```bash
# Build agent Docker image
cd python && docker build -t kaos-agent:latest .

# Build operator
cd operator && go build -o bin/manager main.go

# Generate CRDs after changes
cd operator && make generate && make manifests

# Generate Helm chart from kustomize
cd operator && make helm

# Run operator locally (scale down deployed operator first)
kubectl scale deployment kaos-operator-controller-manager -n kaos-system --replicas=0
cd operator && ./bin/manager

# Run Python tests (34 tests)
cd python && source .venv/bin/activate && python -m pytest tests/ -v

# Run Go integration tests (8 tests with envtest)
cd operator && make test

# Run E2E tests (14 tests, parallel by default)
cd operator/tests && source .venv/bin/activate && make test
```

### Helm Chart

The operator includes a Helm chart in `operator/chart/` generated from kustomize manifests.

```bash
# Install with Helm
helm install kaos-operator operator/chart/ -n kaos-system --create-namespace

# Customize installation
helm install kaos-operator operator/chart/ -n kaos-system --create-namespace \
  --set controllerManager.manager.image.tag=v1.0.0 \
  --set controllerManager.replicas=2

# Uninstall
helm uninstall kaos-operator -n kaos-system
```

Key values in `chart/values.yaml`:
- `controllerManager.manager.image.repository/tag` - Operator image
- `controllerManager.replicas` - Number of replicas
- `controllerManager.manager.resources` - Resource limits
- `defaultImages.*` - Default images for agents/MCP servers

---

## Multi-Agent Delegation Flow

1. Coordinator receives delegation via `/v1/chat/completions` with `role: "delegate"`
2. Coordinator logs `delegation_request` event to memory
3. Coordinator invokes worker via `RemoteAgent.invoke()` using Kubernetes service URL
4. Worker processes task, logs `user_message` and `agent_response` to its memory
5. Coordinator receives response, logs `delegation_response` event
6. Both memories can be verified via `/memory/events` endpoint (when debug enabled)

---

## Deterministic Testing with Mock Responses

### Option 1: Agent-Level Mock (DEBUG_MOCK_RESPONSES)
Set `DEBUG_MOCK_RESPONSES` env var on the Agent to bypass model API entirely:
```yaml
spec:
  config:
    env:
    - name: DEBUG_MOCK_RESPONSES
      value: '["```delegate\n{\"agent\": \"worker\", \"task\": \"process data\"}\n```", "Task completed."]'
```

This is the recommended approach for E2E testing of:
- Tool calling flows (mock response contains tool_call block)
- Agent delegation flows (mock response contains delegate block)
- Memory event chains across multiple agents

### Option 2: LiteLLM Mock Response (API-Level)
LiteLLM also supports `mock_response` in the request body:

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role":"user","content":"hi"}],
    "mock_response": "This is a mock response"
  }'
```

This is useful for testing LiteLLM proxy behavior directly.

---

## Sample Resources

Four self-contained examples are provided in `operator/config/samples/`:

### 1. Simple Echo Agent (`1-simple-echo-agent.yaml`)
Single agent with echo MCP tool and hosted Ollama model (runs in-cluster).
```bash
kubectl apply -f operator/config/samples/1-simple-echo-agent.yaml
# Creates namespace: kaos-simple
# Resources: simple-modelapi (Hosted), simple-echo-mcp, simple-agent
```

### 2. Multi-Agent with MCP (`2-multi-agent-mcp.yaml`)
Coordinator with two workers, all with access to echo MCP tool. Uses hosted Ollama.
```bash
kubectl apply -f operator/config/samples/2-multi-agent-mcp.yaml
# Creates namespace: kaos-multi
# Resources: multi-modelapi (Hosted), multi-echo-mcp, coordinator, worker-1, worker-2
```

### 3. Hierarchical Agents (`3-hierarchical-agents.yaml`)
Complex multi-level hierarchy: supervisor -> team leads -> workers.
Demonstrates `tools.fromString` for dynamic MCP tool creation. Uses hosted Ollama.
```bash
kubectl apply -f operator/config/samples/3-hierarchical-agents.yaml
# Creates namespace: kaos-hierarchy
# Resources: hierarchy-modelapi (Hosted), hierarchy-echo-mcp, hierarchy-calc-mcp,
#            supervisor, research-lead, analysis-lead, researcher-1/2, analyst-1
```

### 4. Development Ollama Proxy (`4-dev-ollama-proxy-agent.yaml`)
For local development with Ollama running on host machine.
Uses LiteLLM proxy with wildcard config to connect to host Ollama.
```bash
kubectl apply -f operator/config/samples/4-dev-ollama-proxy-agent.yaml
# Creates namespace: kaos-dev
# Resources: dev-ollama-proxy (Proxy), dev-echo-mcp, dev-agent
# Requires: Ollama running on host at localhost:11434
```

### MCPServer with Dynamic Tools (tools.fromString)
```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: calc-mcp
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        def calculate(expression: str) -> str:
            """Evaluate a mathematical expression."""
            return str(eval(expression))
```
