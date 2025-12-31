# ModelAPI CRD

The ModelAPI custom resource provides LLM access for agents, either as a proxy to external services or hosting models in-cluster.

## Full Specification

```yaml
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: my-modelapi
  namespace: my-namespace
spec:
  # Required: Deployment mode
  mode: Proxy  # or Hosted
  
  # For Proxy mode: LiteLLM configuration
  proxyConfig:
    # Backend API URL
    apiBase: "http://host.docker.internal:11434"
    
    # Specific model (optional - omit for wildcard mode)
    model: "ollama/smollm2:135m"
    
    # Full LiteLLM config (optional - for advanced routing)
    configYaml: |
      model_list:
        - model_name: "*"
          litellm_params:
            model: "ollama/*"
            api_base: "http://host.docker.internal:11434"
    
    # Environment variables
    env:
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: api-secrets
          key: openai-key
  
  # For Hosted mode: Ollama configuration
  serverConfig:
    # Model to pull and serve
    model: "smollm2:135m"
    
    # Environment variables
    env:
    - name: OLLAMA_DEBUG
      value: "false"
    
    # Resource requirements
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
  endpoint: "http://my-modelapi.my-namespace.svc.cluster.local:8000"
  message: ""
```

## Modes

### Proxy Mode

Uses LiteLLM to proxy requests to external LLM backends.

**Container:** `litellm/litellm:latest`  
**Port:** 8000

#### Wildcard Mode (Recommended for Development)

Proxies any model to the backend:

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

#### CLI Mode (Single Model)

Proxies a specific model only:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "http://host.docker.internal:11434"
    model: "ollama/smollm2:135m"
```

#### Config File Mode (Advanced)

Full control over LiteLLM configuration:

```yaml
spec:
  mode: Proxy
  proxyConfig:
    configYaml: |
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
  serverConfig:
    model: "smollm2:135m"
    resources:
      requests:
        memory: "2Gi"
      limits:
        memory: "8Gi"
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

Backend LLM API URL:

```yaml
proxyConfig:
  apiBase: "http://host.docker.internal:11434"  # Docker Desktop
  # apiBase: "http://ollama.ollama.svc:11434"  # In-cluster Ollama
  # apiBase: "https://api.openai.com"           # OpenAI
```

#### proxyConfig.model

Specific model to proxy (optional):

```yaml
proxyConfig:
  apiBase: "http://localhost:11434"
  model: "ollama/smollm2:135m"
```

When omitted, wildcard mode is used.

#### proxyConfig.configYaml

Full LiteLLM configuration YAML:

```yaml
proxyConfig:
  configYaml: |
    model_list:
      - model_name: "*"
        litellm_params:
          model: "ollama/*"
          api_base: "http://ollama:11434"
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

### serverConfig (for Hosted mode)

#### serverConfig.model

Ollama model to pull and serve:

```yaml
serverConfig:
  model: "smollm2:135m"
  # model: "llama2"
  # model: "mistral"
```

#### serverConfig.env

Environment variables for Ollama:

```yaml
serverConfig:
  env:
  - name: OLLAMA_DEBUG
    value: "true"
```

#### serverConfig.resources

Resource requirements (important for GPU models):

```yaml
serverConfig:
  resources:
    requests:
      memory: "4Gi"
      cpu: "2000m"
    limits:
      memory: "16Gi"
      cpu: "8000m"
      nvidia.com/gpu: "1"  # For GPU acceleration
```

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed |
| `ready` | bool | Whether ModelAPI is ready |
| `endpoint` | string | Service URL for agents |
| `message` | string | Additional status info |

## Examples

### Local Development with Host Ollama

```yaml
apiVersion: ethical.institute/v1alpha1
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
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
spec:
  mode: Hosted
  serverConfig:
    model: "smollm2:135m"
    resources:
      requests:
        memory: "2Gi"
```

### OpenAI Proxy

```yaml
apiVersion: ethical.institute/v1alpha1
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
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: multi-model
spec:
  mode: Proxy
  proxyConfig:
    configYaml: |
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
kubectl get pods -l app=my-modelapi -n my-namespace
kubectl describe pod -l app=my-modelapi -n my-namespace
```

Common causes:
- Image pull errors
- Resource constraints
- For Hosted: Model download in progress

### Connection Errors from Agent

Verify endpoint is accessible:

```bash
kubectl exec -it deploy/my-agent -n my-namespace -- \
  curl http://my-modelapi:8000/health
```

### Model Not Available (Hosted Mode)

Check if model is still downloading:

```bash
kubectl logs -l app=my-modelapi -n my-namespace
```

The model is pulled on startup; large models can take 10+ minutes.
