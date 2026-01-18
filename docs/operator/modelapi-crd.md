# ModelAPI CRD

The ModelAPI custom resource provides LLM access for agents, either as a proxy to external services or hosting models in-cluster.

## Full Specification

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: my-modelapi
  namespace: my-namespace
spec:
  # Required: Deployment mode
  mode: Proxy  # or Hosted
  
  # For Proxy mode: LiteLLM configuration
  proxyConfig:
    # Backend API URL (optional - enables wildcard mode if set without model)
    apiBase: "http://host.docker.internal:11434"
    
    # Specific model (optional - enables single model mode)
    model: "ollama/smollm2:135m"
    
    # Full config YAML (optional - for advanced multi-model routing)
    configYaml:
      fromString: |
        model_list:
          - model_name: "*"
            litellm_params:
              model: "ollama/*"
              api_base: "http://host.docker.internal:11434"
      # Or load from secret:
      # fromSecretKeyRef:
      #   name: litellm-config
      #   key: config.yaml
    
    # Environment variables
    env:
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: api-secrets
          key: openai-key
  
  # For Hosted mode: Ollama configuration
  hostedConfig:
    # Model to pull and serve (loaded in an initContainer)
    model: "smollm2:135m"
    
    # Environment variables
    env:
    - name: OLLAMA_DEBUG
      value: "false"

  # Optional: PodSpec override using strategic merge patch
  podSpec:
    containers:
    - name: model-api  # Must match generated container name
      resources:
        requests:
          memory: "2Gi"
          cpu: "1000m"
        limits:
          memory: "8Gi"
          cpu: "4000m"

status:
  phase: Ready           # Pending, Ready, Failed
  ready: true
  endpoint: "http://modelapi-my-modelapi.my-namespace.svc.cluster.local:8000"
  message: ""
```

## Modes

### Proxy Mode

Uses LiteLLM to proxy requests to external LLM backends.

**Container:** `litellm/litellm:latest`  
**Port:** 8000

#### Wildcard Mode (Recommended for Development)

Proxies any model to the backend (set `apiBase` without `model`):

```yaml
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "http://host.docker.internal:11434"
    # No model specified = wildcard
```

Agents can request any model:
- `ollama/smollm2:135m`
- `ollama/llama2`
- `ollama/mistral`

#### Mock Mode (For Testing)

Set `model` without `apiBase` for mock testing:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    model: "gpt-3.5-turbo"  # Model name only, no backend
```

Supports `mock_response` in request body for deterministic tests.

#### Config File Mode (Advanced)

Full control over LiteLLM configuration:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    configYaml:
      fromString: |
        model_list:
          - model_name: "gpt-4"
            litellm_params:
              model: "azure/gpt-4"
              api_base: "https://my-azure.openai.azure.com"
              api_key: "os.environ/AZURE_API_KEY"
          
          - model_name: "claude"
            litellm_params:
              model: "claude-3-sonnet-20240229"
              api_key: "os.environ/ANTHROPIC_API_KEY"
    
    env:
    - name: AZURE_API_KEY
      valueFrom:
        secretKeyRef:
          name: llm-secrets
          key: azure-key
    - name: ANTHROPIC_API_KEY
      valueFrom:
        secretKeyRef:
          name: llm-secrets
          key: anthropic-key
```

### Hosted Mode

Runs Ollama in-cluster with the specified model.

**Container:** `ollama/ollama:latest`  
**Port:** 11434

```yaml
spec:
  mode: Hosted
  hostedConfig:
    model: "smollm2:135m"
```

**How it works:**
- An init container starts Ollama, pulls the specified model, then exits
- The model is stored in a shared volume
- The main Ollama container starts with the model already available
- First pod startup may take 1-2 minutes depending on model size

## Spec Fields

### mode (required)

| Value | Description |
|-------|-------------|
| `Proxy` | LiteLLM proxy to external backend |
| `Hosted` | Ollama running in-cluster |

### proxyConfig (for Proxy mode)

#### proxyConfig.apiBase

Backend LLM API URL (optional):

```yaml
proxyConfig:
  apiBase: "http://host.docker.internal:11434"  # Docker Desktop
  # apiBase: "http://ollama.ollama.svc:11434"  # In-cluster Ollama
  # apiBase: "https://api.openai.com"           # OpenAI
```

When set without `model`, enables wildcard mode.

#### proxyConfig.model

Specific model to proxy (optional):

```yaml
proxyConfig:
  apiBase: "http://localhost:11434"
  model: "ollama/smollm2:135m"
```

When set without `apiBase`, enables mock testing mode.

#### proxyConfig.configYaml

Full LiteLLM configuration:

```yaml
proxyConfig:
  configYaml:
    fromString: |
      model_list:
        - model_name: "*"
          litellm_params:
            model: "ollama/*"
            api_base: "http://ollama:11434"
    # Or from secret:
    # fromSecretKeyRef:
    #   name: litellm-config
    #   key: config.yaml
```

When provided, `apiBase` and `model` are ignored.

#### proxyConfig.env

Environment variables for the LiteLLM container:

```yaml
proxyConfig:
  env:
  - name: OPENAI_API_KEY
    valueFrom:
      secretKeyRef:
        name: secrets
        key: openai
```

### hostedConfig (for Hosted mode)

#### hostedConfig.model

Ollama model to pull and serve:

```yaml
hostedConfig:
  model: "smollm2:135m"
  # model: "llama2"
  # model: "mistral"
```

#### hostedConfig.env

Environment variables for Ollama:

```yaml
hostedConfig:
  env:
  - name: OLLAMA_DEBUG
    value: "true"
```

### podSpec (optional)

Override the generated pod spec using Kubernetes strategic merge patch:

```yaml
spec:
  podSpec:
    containers:
    - name: model-api  # Must match the generated container name
      resources:
        requests:
          memory: "4Gi"
          cpu: "2000m"
        limits:
          memory: "16Gi"
          cpu: "8000m"
          nvidia.com/gpu: "1"  # For GPU acceleration
```

### gatewayRoute (optional)

Configure Gateway API routing, including request timeout:

```yaml
spec:
  gatewayRoute:
    # Request timeout for the HTTPRoute (Gateway API Duration format)
    # Default: "120s" for ModelAPI, "120s" for Agent, "30s" for MCPServer
    # Set to "0s" to use Gateway's default timeout
    timeout: "120s"
```

This is especially useful for LLM inference which can take longer than typical HTTP timeouts:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama-proxy
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "http://ollama.default:11434"
  gatewayRoute:
    timeout: "5m"  # 5 minutes for slow inference
```

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed |
| `ready` | bool | Whether ModelAPI is ready |
| `endpoint` | string | Service URL for agents |
| `message` | string | Additional status info |
| `deployment` | object | Deployment status for rolling update visibility |

### deployment (status)

Mirrors key status fields from the underlying Kubernetes Deployment:

| Field | Type | Description |
|-------|------|-------------|
| `replicas` | int32 | Total number of non-terminated pods |
| `readyReplicas` | int32 | Number of pods with Ready condition |
| `availableReplicas` | int32 | Number of available pods |
| `updatedReplicas` | int32 | Number of pods with desired template (rolling update progress) |
| `conditions` | array | Deployment conditions (Available, Progressing, ReplicaFailure) |

## Examples

### Local Development with Host Ollama

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: dev-ollama
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "http://host.docker.internal:11434"
```

### In-Cluster Ollama

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
spec:
  mode: Hosted
  hostedConfig:
    model: "smollm2:135m"
  podSpec:
    containers:
    - name: model-api
      resources:
        requests:
          memory: "2Gi"
```

### Mock Testing Mode

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: mock-api
spec:
  mode: Proxy
  proxyConfig:
    model: "gpt-3.5-turbo"
```

### OpenAI Proxy

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: openai
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "https://api.openai.com"
    model: "gpt-4o-mini"
    env:
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: openai-secrets
          key: api-key
```

### Multi-Model Routing

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: multi-model
spec:
  mode: Proxy
  proxyConfig:
    configYaml:
      fromString: |
        model_list:
          - model_name: "fast"
            litellm_params:
              model: "ollama/smollm2:135m"
              api_base: "http://ollama:11434"
          
          - model_name: "smart"
            litellm_params:
              model: "gpt-4o"
              api_key: "os.environ/OPENAI_API_KEY"
    
    env:
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: secrets
          key: openai
```

## Troubleshooting

### ModelAPI Stuck in Pending

Check pod status:

```bash
kubectl get pods -l modelapi=my-modelapi -n my-namespace
kubectl describe pod -l modelapi=my-modelapi -n my-namespace
```

Common causes:
- Image pull errors
- Resource constraints
- For Hosted: Model download in progress

### Connection Errors from Agent

Verify endpoint is accessible:

```bash
kubectl exec -it deploy/agent-my-agent -n my-namespace -- \
  curl http://modelapi-my-modelapi:8000/health
```

### Model Not Available (Hosted Mode)

Check if model is still downloading:

```bash
kubectl logs -l modelapi=my-modelapi -n my-namespace -c pull-model
```

The model is pulled on startup; large models can take 10+ minutes.
