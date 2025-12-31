# Environment Variables Reference

Complete reference for all environment variables used by the Agentic Kubernetes Operator.

## Agent Container Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_NAME` | Unique agent identifier | `my-agent` |
| `MODEL_API_URL` | Base URL for LLM API | `http://modelapi:8000` |

### Agent Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_DESCRIPTION` | Human-readable description | `AI Agent` |
| `AGENT_INSTRUCTIONS` | System prompt for the agent | `You are a helpful assistant.` |
| `AGENT_PORT` | Server port | `8000` |
| `AGENT_LOG_LEVEL` | Logging level | `INFO` |

### Model Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_NAME` | Model identifier for LLM calls | `smollm2:135m` |

### Agentic Loop Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTIC_LOOP_MAX_STEPS` | Maximum reasoning iterations | `5` |
| `AGENTIC_LOOP_ENABLE_TOOLS` | Enable tool calling | `true` |
| `AGENTIC_LOOP_ENABLE_DELEGATION` | Enable agent delegation | `true` |

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

### Debug Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_DEBUG_MEMORY_ENDPOINTS` | Enable `/memory/*` endpoints | `false` |

## MCP Server Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_HOST` | Server bind address | `0.0.0.0` |
| `MCP_PORT` | Server port | `8000` |
| `MCP_TOOLS_STRING` | Python code defining tools | `""` |
| `MCP_LOG_LEVEL` | Logging level | `INFO` |

## Operator-Set Variables

The operator automatically sets these variables on agent pods:

### From Agent CRD

| CRD Field | Environment Variable |
|-----------|---------------------|
| `metadata.name` | `AGENT_NAME` |
| `config.description` | `AGENT_DESCRIPTION` |
| `config.instructions` | `AGENT_INSTRUCTIONS` |
| `config.agenticLoop.maxSteps` | `AGENTIC_LOOP_MAX_STEPS` |
| `config.agenticLoop.enableTools` | `AGENTIC_LOOP_ENABLE_TOOLS` |
| `config.agenticLoop.enableDelegation` | `AGENTIC_LOOP_ENABLE_DELEGATION` |

### From Referenced Resources

| Source | Environment Variable |
|--------|---------------------|
| ModelAPI.status.endpoint | `MODEL_API_URL` |
| `agentNetwork.access` list | `PEER_AGENTS` |
| Each peer agent service URL | `PEER_AGENT_<NAME>_CARD_URL` |

### Always Set

| Variable | Value |
|----------|-------|
| `AGENT_DEBUG_MEMORY_ENDPOINTS` | `true` |

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

## ModelAPI Environment Variables

### Proxy Mode (LiteLLM)

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

## Environment Variable Precedence

For agent pods, environment variables are applied in this order:

1. Operator-generated variables (from CRD fields)
2. `config.env` variables (can override operator-generated)

Example:

```yaml
spec:
  config:
    env:
    - name: MODEL_NAME
      value: "gpt-4"  # Overrides default smollm2:135m
```

## Debugging Environment Variables

Check environment variables on a running pod:

```bash
kubectl exec -it deploy/my-agent -n my-namespace -- env | sort
```

Expected output:
```
AGENT_DEBUG_MEMORY_ENDPOINTS=true
AGENT_DESCRIPTION=My agent
AGENT_INSTRUCTIONS=You are helpful.
AGENT_NAME=my-agent
AGENTIC_LOOP_ENABLE_DELEGATION=true
AGENTIC_LOOP_ENABLE_TOOLS=true
AGENTIC_LOOP_MAX_STEPS=5
MODEL_API_URL=http://modelapi.my-namespace.svc.cluster.local:8000
MODEL_NAME=smollm2:135m
PEER_AGENTS=worker-1,worker-2
PEER_AGENT_WORKER_1_CARD_URL=http://worker-1.my-namespace.svc.cluster.local
PEER_AGENT_WORKER_2_CARD_URL=http://worker-2.my-namespace.svc.cluster.local
```
