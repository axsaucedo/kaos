# Model API Configurations

This directory contains different approaches for deploying model APIs (LLM endpoints) that agents can connect to. Each approach is a different way to provide OpenAI-compatible API endpoints to agents.

## Overview

The agentic Kubernetes operator supports two ModelAPI deployment approaches:

| Approach | Use Case | Components | Location |
|----------|----------|------------|----------|
| **LiteLLM Proxy** | Development/testing with existing Ollama | LiteLLM proxy + Ollama | `model-api/litellm/` |
| **vLLM Hosted** | Production isolated deployment | vLLM in-cluster | `model-api/vllm/` |

---

## 1. LiteLLM Proxy (Proxy Mode)

**Purpose**: Route OpenAI-compatible API calls to an external/existing Ollama server.

**Best for**:
- Local development
- Testing against existing Ollama instance
- Shared model server setup
- Non-Kubernetes environments

### Architecture

```
┌─────────────────────────────────────┐
│ Agents (localhost:8000-8002)        │
│                                     │
│ POST /v1/chat/completions           │
└────────────────┬────────────────────┘
                 │
         HTTP OpenAI-compatible
                 │
    ┌────────────▼─────────────┐
    │ LiteLLM Proxy            │
    │ (localhost:4000)         │
    │                          │
    │ - Routes requests        │
    │ - OpenAI API compatible  │
    │ - Model selection        │
    └────────────┬─────────────┘
                 │
        HTTP to Ollama format
                 │
    ┌────────────▼─────────────┐
    │ Ollama                   │
    │ (localhost:11434)        │
    │                          │
    │ - SmolLM2-135M           │
    │ - Llama2                 │
    │ - Neural-Chat            │
    └──────────────────────────┘
```

### Quick Start

#### Prerequisites
```bash
# 1. Start Ollama
ollama serve

# 2. Pull model
ollama pull smollm2:135m

# 3. Have Docker installed
docker --version
```

#### Run LiteLLM Proxy Locally

```bash
cd model-api/litellm

# Start proxy with docker-compose
docker-compose up -d

# Verify it's running
curl http://localhost:4000/models
```

#### Test Agent Against LiteLLM

```bash
# Run agent test pointing to LiteLLM
MODEL_API_URL=http://localhost:4000 \
python3 agent/examples/simple-math-agent/agent.py
```

### Configuration

**File**: `model-api/litellm/config.yaml`

Key settings:
```yaml
model_list:
  - model_name: "smollm2:135m"
    litellm_params:
      model: "ollama/smollm2:135m"
      api_base: "http://host.docker.internal:11434"  # Ollama URL
      stream_timeout: 600
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm-proxy
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: litellm
        image: ghcr.io/berri-ai/litellm:latest
        ports:
        - containerPort: 4000
        env:
        - name: LITELLM_MODE
          value: "proxy"
        - name: OLLAMA_BASE_URL
          value: "http://ollama-service:11434"
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
      volumes:
      - name: config
        configMap:
          name: litellm-config
```

---

## 2. vLLM Hosted (Hosted Mode)

**Purpose**: Run a vLLM instance inside the Kubernetes cluster or Docker.

**Best for**:
- Production Kubernetes deployments
- Isolated cluster (no external Ollama dependency)
- GPU acceleration
- Model versioning/pinning
- Self-contained environments

### Quick Start

#### Local Testing with Docker Compose

```bash
cd model-api/vllm

# Option 1: Simple CPU-friendly setup (TinyLlama)
docker-compose -f docker-compose-simple.yaml up -d

# Option 2: Better quality (Llama-2-7B, needs more RAM)
docker-compose up -d

# Verify it's running
curl http://localhost:8001/models
```

#### Test Agent Against vLLM

```bash
# Using TinyLlama (simple setup)
export MODEL_API_URL=http://localhost:8001/v1
export MODEL_NAME=tinyllama

# Run test
python3 agent/examples/simple-math-agent/agent.py
```

### Kubernetes Deployment

See `model-api/vllm/README.md` for:
- Deployment manifest
- GPU support
- Model caching
- Scaling configuration

**Quick example**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm
spec:
  template:
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        env:
        - name: MODEL_NAME
          value: "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
        - name: SERVED_MODEL_NAME
          value: "tinyllama"
```

### Available Models

| Model | Size | Best For |
|-------|------|----------|
| TinyLlama-1.1B | 1.1B | CPU testing, fast inference |
| Llama-2-7B | 7B | Balanced quality/speed |
| Mistral-7B | 7B | Fast, good quality |

See `model-api/vllm/README.md` for more models and configuration options.

---

## Switching Between Approaches

### For Local Testing

**Using LiteLLM proxy** (connects to Ollama):
```bash
export MODEL_API_URL=http://localhost:4000/v1
python3 agent/examples/simple-math-agent/agent.py
```

**Using vLLM** (standalone):
```bash
export MODEL_API_URL=http://localhost:8001/v1
export MODEL_NAME=tinyllama
python3 agent/examples/simple-math-agent/agent.py
```

**Using direct Ollama**:
```bash
export MODEL_API_URL=http://localhost:11434/v1
python3 agent/examples/simple-math-agent/agent.py
```

### For Kubernetes

Update the Agent CRD:
```yaml
apiVersion: agentic.example.com/v1alpha1
kind: Agent
metadata:
  name: my-agent
spec:
  modelAPI: litellm-proxy  # or vllm-hosted
```

The operator controller uses the referenced ModelAPI resource to inject the correct endpoint.

---

## Troubleshooting

### LiteLLM proxy won't start
```bash
# Check logs
docker-compose logs litellm-proxy

# Verify Ollama is running
curl http://localhost:11434/api/tags

# Check port 4000 is free
lsof -i :4000
```

### Agent can't connect to LiteLLM
```bash
# Test LiteLLM directly
curl http://localhost:4000/models

# Test with model request
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"smollm2:135m","messages":[{"role":"user","content":"test"}]}'
```

### Docker network issues on Mac
```bash
# Use host.docker.internal instead of localhost
# (Already configured in docker-compose.yaml)
```

---

## Next Steps

1. **Test LiteLLM locally** → Run simple-math-agent with LiteLLM proxy
2. **Test vLLM** → Set up vLLM approach (Phase 5.2)
3. **Deploy to K8s** → Use operator to deploy ModelAPI resources
4. **Monitor** → Check logs and metrics
