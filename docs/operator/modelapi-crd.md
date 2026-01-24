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
    # Required: List of supported models
    # Supports specific models or wildcards (openai/*, *)
    models:
    - "openai/gpt-4o"
    - "anthropic/claude-3-sonnet"
    # - "*"              # Wildcard: any model
    # - "openai/*"       # Provider wildcard: any openai model
    
    # Backend API URL (optional - used as api_base for all models)
    apiBase: "https://api.openai.com"
    
    # API key for authentication (optional - used for all models)
    apiKey:
      value: "sk-..."  # Direct value (not recommended for production)
      # Or from secret:
      # valueFrom:
      #   secretKeyRef:
      #     name: api-secrets
      #     key: openai-key
      # Or from configmap:
      # valueFrom:
      #   configMapKeyRef:
      #     name: api-config
      #     key: api-key
    
    # Full config YAML (optional - for advanced multi-model routing)
    # When provided, models list is used for agent validation only
    configYaml:
      fromString: |
        model_list:
          - model_name: "openai/gpt-4o"
            litellm_params:
              model: "openai/gpt-4o"
              api_key: "os.environ/PROXY_API_KEY"
    
    # Environment variables
    env:
    - name: CUSTOM_ENV
      value: "value"
  
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
  supportedModels:       # Models this ModelAPI supports
  - "openai/gpt-4o"
  - "anthropic/claude-3-sonnet"
```

## Modes

### Proxy Mode

Uses LiteLLM to proxy requests to external LLM backends.

**Container:** `ghcr.io/berriai/litellm:main-latest`  
**Port:** 8000

#### Basic Configuration

Configure models with optional apiBase and apiKey:

```yaml
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

This generates the following LiteLLM config:

```yaml
model_list:
  - model_name: "openai/gpt-4o"
    litellm_params:
      model: "openai/gpt-4o"
      api_base: "os.environ/PROXY_API_BASE"
      api_key: "os.environ/PROXY_API_KEY"
  - model_name: "openai/gpt-4o-mini"
    litellm_params:
      model: "openai/gpt-4o-mini"
      api_base: "os.environ/PROXY_API_BASE"
      api_key: "os.environ/PROXY_API_KEY"
litellm_settings:
  drop_params: true
```

#### Wildcard Mode (Passthrough)

When using wildcards in the `models` list, the ModelAPI generates a passthrough configuration that allows clients to specify any model:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "*"  # Allow any model - generates passthrough config
    apiBase: "http://host.docker.internal:11434"
```

Provider-specific wildcards also trigger passthrough mode:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "nebius/*"  # Allow any Nebius model
    apiKey:
      valueFrom:
        secretKeyRef:
          name: nebius-secrets
          key: api-key
```

This generates the following LiteLLM passthrough config:

```yaml
model_list:
  - model_name: "*"
    litellm_params:
      model: "*"
      api_key: "os.environ/PROXY_API_KEY"
litellm_settings:
  drop_params: true
```

With passthrough mode:
- Agents specify the full model name (e.g., `nebius/Qwen/Qwen3-235B-A22B`)
- LiteLLM routes requests based on the model prefix (e.g., `nebius/` goes to Nebius provider)
- The `models` list in the CRD is used for agent validation only

#### Config File Mode (Advanced)

For complex configurations, provide a full LiteLLM config:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    # models list is required for agent validation
    models:
    - "gpt-4"
    - "claude-3"
    configYaml:
      fromString: |
        model_list:
          - model_name: "gpt-4"
            litellm_params:
              model: "azure/gpt-4"
              api_base: "https://my-azure.openai.azure.com"
              api_key: "os.environ/AZURE_API_KEY"
          
          - model_name: "claude-3"
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

**Note:** When `configYaml` is provided, the `models` list is still required but used only for agent model validation. The `apiKey` and `apiBase` are set as environment variables (`PROXY_API_KEY`, `PROXY_API_BASE`) but not injected into the config.

### Hosted Mode

Runs Ollama in-cluster with the specified model.

**Container:** `alpine/ollama:latest`  
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

#### proxyConfig.models (required)

List of supported models. Agents referencing this ModelAPI must use a model that matches this list.

```yaml
proxyConfig:
  models:
  - "openai/gpt-4o"           # Specific model
  - "anthropic/*"             # Provider wildcard
  - "*"                       # Full wildcard (any model)
```

Models are validated against this list when Agents are created. Supports:
- Exact match: `openai/gpt-4o`
- Provider wildcards: `openai/*` matches `openai/gpt-4o`, `openai/gpt-4o-mini`
- Full wildcard: `*` matches any model

#### proxyConfig.apiBase (optional)

Backend LLM API URL:

```yaml
proxyConfig:
  apiBase: "http://host.docker.internal:11434"  # Docker Desktop
  # apiBase: "http://ollama.ollama.svc:11434"  # In-cluster Ollama
  # apiBase: "https://api.openai.com"           # OpenAI
```

Set as `PROXY_API_BASE` environment variable and used as `api_base` in generated LiteLLM config.

#### proxyConfig.apiKey (optional)

API key for LLM backend authentication:

```yaml
proxyConfig:
  apiKey:
    value: "sk-..."  # Direct value (use for testing only)
```

Or from a secret (recommended):

```yaml
proxyConfig:
  apiKey:
    valueFrom:
      secretKeyRef:
        name: api-secrets
        key: openai-key
```

Or from a ConfigMap:

```yaml
proxyConfig:
  apiKey:
    valueFrom:
      configMapKeyRef:
        name: api-config
        key: api-key
```

Set as `PROXY_API_KEY` environment variable and used as `api_key` in generated LiteLLM config.

#### proxyConfig.configYaml (optional)

Full LiteLLM configuration for advanced use cases:

```yaml
proxyConfig:
  configYaml:
    fromString: |
      model_list:
        - model_name: "gpt-4"
          litellm_params:
            model: "openai/gpt-4"
            api_key: "os.environ/PROXY_API_KEY"
    # Or from secret:
    # fromSecretKeyRef:
    #   name: litellm-config
    #   key: config.yaml
```

When provided:
- The `models` list is validated against `model_name` entries in the config
- `apiKey` and `apiBase` are available as `PROXY_API_KEY` and `PROXY_API_BASE` env vars
- The provided config is used directly (not generated)

#### proxyConfig.env

Additional environment variables for the LiteLLM container:

```yaml
proxyConfig:
  env:
  - name: CUSTOM_HEADER
    value: "my-value"
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

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed |
| `ready` | bool | Whether ModelAPI is ready |
| `endpoint` | string | Service URL for agents |
| `message` | string | Additional status info |
| `supportedModels` | []string | Models this ModelAPI supports |
| `deployment` | object | Deployment status for rolling update visibility |

### supportedModels (status)

List of models supported by this ModelAPI. Used by the Agent controller to validate that an Agent's model is supported:

```yaml
status:
  supportedModels:
  - "openai/gpt-4o"
  - "anthropic/*"
```

### deployment (status)

Mirrors key status fields from the underlying Kubernetes Deployment:

| Field | Type | Description |
|-------|------|-------------|
| `replicas` | int32 | Total number of non-terminated pods |
| `readyReplicas` | int32 | Number of pods with Ready condition |
| `availableReplicas` | int32 | Number of available pods |
| `updatedReplicas` | int32 | Number of pods with desired template |
| `conditions` | array | Deployment conditions |

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
    models:
    - "*"
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

### OpenAI Direct

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: openai
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

### Nebius AI Studio

Use the wildcard pattern to allow any Nebius model. Agents specify the full model name (e.g., `nebius/Qwen/Qwen3-235B-A22B`):

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: nebius
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "nebius/*"  # Allows any Nebius model (passthrough mode)
    apiKey:
      valueFrom:
        secretKeyRef:
          name: nebius-secrets
          key: api-key
---
# Agent using this ModelAPI
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
spec:
  modelAPI: nebius
  model: "nebius/Qwen/Qwen3-235B-A22B"  # Full model name
  config:
    description: "Agent using Nebius AI"
```

See [LiteLLM Nebius docs](https://docs.litellm.ai/docs/providers/nebius) for supported models.

### LiteLLM Gateway Proxy

Proxy to another LiteLLM instance acting as a gateway:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: litellm-gateway
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "litellm_proxy/*"
    apiBase: "http://litellm-gateway.infra.svc:8000"
    apiKey:
      valueFrom:
        secretKeyRef:
          name: litellm-secrets
          key: api-key
```

### Multi-Provider with Custom Config

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: multi-provider
spec:
  mode: Proxy
  proxyConfig:
    models:
    - "gpt-4"
    - "claude-3"
    - "llama-3"
    configYaml:
      fromString: |
        model_list:
          - model_name: "gpt-4"
            litellm_params:
              model: "azure/gpt-4"
              api_base: "https://my-azure.openai.azure.com"
              api_key: "os.environ/AZURE_API_KEY"
          
          - model_name: "claude-3"
            litellm_params:
              model: "claude-3-sonnet-20240229"
              api_key: "os.environ/ANTHROPIC_API_KEY"
          
          - model_name: "llama-3"
            litellm_params:
              model: "ollama/llama3"
              api_base: "http://ollama:11434"
        
        litellm_settings:
          drop_params: true
          request_timeout: 120
    
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

## Design Decisions

### Model Validation Behavior

The Agent controller validates the Agent's `model` against the ModelAPI's `supportedModels` at creation time. However:

- **No reverse validation on ModelAPI changes**: If a ModelAPI's supported models change after Agents are created, existing Agents are not automatically invalidated
- **Discovery at runtime**: Agents may fail at runtime if the model is no longer supported
- **Rolling updates trigger revalidation**: A new Agent deployment will fail to start if model validation fails

This design avoids the complexity of maintaining bidirectional state between Agents and ModelAPIs.

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

### ModelAPI in Failed State

Check status message:

```bash
kubectl get modelapi my-modelapi -o jsonpath='{.status.message}'
```

Common causes:
- `configYaml` validation failed (model_name not in models list)
- Invalid YAML in configYaml

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
