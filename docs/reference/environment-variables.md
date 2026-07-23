# Environment Variables Reference

Complete reference for all environment variables used by the KAOS.

## Agent Container Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_NAME` | Unique agent identifier | `my-agent` |
| `MODEL_API_URL` | Base URL for LLM API | `http://modelapi:8000` |
| `MODEL_NAME` | Model identifier for LLM calls | `openai/gpt-4o` |

### Agent Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_DESCRIPTION` | Human-readable description | `AI Agent` |
| `AGENT_INSTRUCTIONS` | System prompt for the agent | `You are a helpful assistant.` |
| `AGENT_PORT` | Server port | `8000` |
| `AGENT_LOG_LEVEL` | Logging level | `INFO` |

### Agentic Loop Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTIC_LOOP_MAX_STEPS` | Maximum reasoning iterations | `5` |

### Memory Configuration

Injected by the operator on memory-enabled agents. For the full model see [Memory Architecture](../operator/memory-architecture.md).

| Variable | Description | Default |
|----------|-------------|---------|
| `MEMORY_ENABLED` | Enable/disable memory (uses NullMemory when disabled) | `true` |
| `MEMORY_TYPE` | Backend: `local` (pod-local short-term) or `remote` (bound MemoryStore) | derived |
| `MEMORY_STORE_ENDPOINT` | Memory service URL; injected only for `remote` (selects `RemoteMemory`) | — |
| `MEMORY_MAX_READ_SCOPE` | Automatic recall scope and `search_memory` ceiling: `session`, `agent`, or `user` | `session` |
| `MEMORY_REQUIRE_PRINCIPAL` | Require verified principal attribution on writes and narrow agent reads | posture-derived |
| `MEMORY_REQUIRE_AGENT_IDENTITY` | Require stable agent attribution on writes | posture-derived |
| `MEMORY_TOOLS` | Explicit memory tools: `all`, `read`, `write` (unset = none) | — |
| `MEMORY_FAILURE_MODE` | Write/forget failure mode: `soft` or `strict` | store default |
| `MEMORY_SHORT_TERM_TOKEN_BUDGET` | Verbatim short-term window cap, in tokens | runtime default |
| `MEMORY_ROLLING_SUMMARY` | Keep a medium-term rolling digest of evicted turns | `true` |
| `AGENT_IDENTITY` | Verifiable agent principal (`kaos://agent/<ns>/<name>`) anchoring agent scope | always set |
| `MEMORY_CONTEXT_LIMIT` | Recent history events replayed / forwarded on delegation (runtime default) | `6` |
| `MEMORY_MAX_SESSIONS` | Max sessions kept (LocalMemory runtime default) | `1000` |
| `MEMORY_MAX_SESSION_EVENTS` | Max events per session (LocalMemory runtime default) | `500` |

The first block (`MEMORY_ENABLED` … `AGENT_IDENTITY`) is injected by the operator from the Agent `config.memory` block and the bound MemoryStore. The last three are runtime defaults consumed by the LocalMemory backend and the delegation context; they are not injected from CRD fields.

### Sub-Agent Configuration

**Direct Format:**

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_SUB_AGENTS` | Comma-separated name:url pairs | `worker-1:http://w1:8000,worker-2:http://w2:8000` |

**Kubernetes Format:**

| Variable | Description | Example |
|----------|-------------|---------|
| `PEER_AGENTS` | Comma-separated agent names | `worker-1,worker-2` |
| `PEER_AGENT_<NAME>_CARD_URL` | Individual agent URLs | `http://worker-1.ns.svc:80` |

Note: Replace `-` with `_` and use uppercase for variable name (e.g., `worker-1` → `PEER_AGENT_WORKER_1_CARD_URL`).

### Logging Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_ACCESS_LOG` | Enable uvicorn access logs | `false` |

## MCP Server Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_HOST` | Server bind address | `0.0.0.0` |
| `MCP_PORT` | Server port | `8000` |
| `MCP_TOOLS_STRING` | Python code defining tools | `""` |
| `MCP_LOG_LEVEL` | Logging level | `INFO` |
| `MCP_ACCESS_LOG` | Enable uvicorn access logs | `false` |

## ModelAPI Environment Variables

### Proxy Mode (LiteLLM)

The operator automatically sets these environment variables based on ModelAPI spec:

| Variable | Source | Description |
|----------|--------|-------------|
| `PROXY_API_KEY` | `proxyConfig.apiKey` | API key for LLM backend |
| `PROXY_API_BASE` | `proxyConfig.apiBase` | Base URL for LLM backend |

These are used in the generated LiteLLM config:

```yaml
model_list:
  - model_name: "openai/gpt-4o"
    litellm_params:
      model: "openai/gpt-4o"
      api_key: "os.environ/PROXY_API_KEY"
      api_base: "os.environ/PROXY_API_BASE"
```

#### Custom Environment Variables

Add custom variables via `proxyConfig.env`:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `AZURE_API_KEY` | Azure OpenAI API key |
| Any LiteLLM-supported var | See LiteLLM documentation |

### Hosted Mode (Ollama)

| Variable | Description |
|----------|-------------|
| `OLLAMA_DEBUG` | Enable debug logging |
| `OLLAMA_HOST` | Host to bind to |
| `OLLAMA_MODELS` | Model directory path |
| Any Ollama-supported var | See Ollama documentation |

## Operator-Set Variables

The operator automatically sets these variables on agent pods:

### From Agent CRD

| CRD Field | Environment Variable |
|-----------|---------------------|
| `metadata.name` | `AGENT_NAME` |
| `spec.model` | `MODEL_NAME` |
| `config.description` | `AGENT_DESCRIPTION` |
| `config.instructions` | `AGENT_INSTRUCTIONS` |
| `config.reasoningLoopMaxSteps` | `AGENTIC_LOOP_MAX_STEPS` |
| `config.memory.enabled` | `MEMORY_ENABLED` |
| `config.memory.type` | `MEMORY_TYPE` |
| `config.memory.maxReadScope` | `MEMORY_MAX_READ_SCOPE` |
| `config.memory.tools` | `MEMORY_TOOLS` |
| `config.memory.failureMode` | `MEMORY_FAILURE_MODE` |
| `config.memory.clientParams.tokenBudget` | `MEMORY_SHORT_TERM_TOKEN_BUDGET` |
| `config.memory.clientParams.rollingSummary` | `MEMORY_ROLLING_SUMMARY` |
| MemoryStore endpoint (remote only) | `MEMORY_STORE_ENDPOINT` |
| `kaos://agent/<ns>/<name>` (always) | `AGENT_IDENTITY` |

### From Referenced Resources

| Source | Environment Variable |
|--------|---------------------|
| ModelAPI.status.endpoint | `MODEL_API_URL` |
| `agentNetwork.access` list | `PEER_AGENTS` |
| Each peer agent service URL | `PEER_AGENT_<NAME>_CARD_URL` |

## Custom Environment Variables

Add custom variables via `config.env`:

```yaml
spec:
  config:
    env:
    - name: CUSTOM_VAR
      value: "my-value"
    - name: SECRET_VAR
      valueFrom:
        secretKeyRef:
          name: my-secrets
          key: secret-key
    - name: CONFIG_VAR
      valueFrom:
        configMapKeyRef:
          name: my-config
          key: config-key
```

**Note:** `MODEL_NAME` is automatically set from `spec.model` and should not be overridden via `config.env`.

## Environment Variable Precedence

For agent pods, environment variables are applied in this order:

1. Operator-generated variables (from CRD fields)
2. `config.env` variables (can override operator-generated)

## Debugging Environment Variables

Check environment variables on a running pod:

```bash
kubectl exec -it deploy/agent-my-agent -n my-namespace -- env | sort
```

Expected output:
```
AGENT_DESCRIPTION=My agent
AGENT_INSTRUCTIONS=You are helpful.
AGENT_NAME=my-agent
AGENTIC_LOOP_MAX_STEPS=5
MEMORY_ENABLED=true
MEMORY_TYPE=local
MEMORY_CONTEXT_LIMIT=6
MODEL_API_URL=http://modelapi.my-namespace.svc.cluster.local:8000
MODEL_NAME=openai/gpt-4o
PEER_AGENTS=worker-1,worker-2
PEER_AGENT_WORKER_1_CARD_URL=http://worker-1.my-namespace.svc.cluster.local
PEER_AGENT_WORKER_2_CARD_URL=http://worker-2.my-namespace.svc.cluster.local
```
