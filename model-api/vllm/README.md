# vLLM Hosted Model Deployment

This directory contains vLLM setup for hosting LLM models inside containers/Kubernetes. vLLM provides high-performance OpenAI-compatible API endpoints.

## Overview

**vLLM Hosted Mode** is best for:
- Production Kubernetes deployments
- Isolated cluster (no external Ollama dependency)
- Running specific model versions
- GPU acceleration (optional)
- Scaling model replicas

---

## Quick Start: Docker Compose

### Option 1: Simple (CPU-friendly, TinyLlama)

For quick testing without GPU:

```bash
cd model-api/vllm

# Start vLLM with TinyLlama-1.1B
docker-compose -f docker-compose-simple.yaml up -d

# Wait for startup (~30-60 seconds for first run, model download)
sleep 60

# Test it
curl http://localhost:8001/models
```

### Option 2: Production (Llama-2-7B)

For better model quality (requires more RAM):

```bash
cd model-api/vllm

# Start vLLM with Llama-2-7B
docker-compose up -d

# Wait for startup (model is 13GB, first download takes time)
```

---

## Available Models

### Recommended (Docker Compose)

| Model | Size | Speed | Quality | Type |
|-------|------|-------|---------|------|
| **TinyLlama** | 1.1B | Fast ⚡ | Basic | CPU-friendly |
| **Llama-2-7B** | 7B | Medium | Good | GPU recommended |

### Other Models (manually configured)

Edit `docker-compose.yaml` `MODEL_NAME` environment variable:

```yaml
environment:
  - MODEL_NAME=mistralai/Mistral-7B-Instruct-v0.1
  - SERVED_MODEL_NAME=mistral
```

Available models from HuggingFace:
- `TinyLlama/TinyLlama-1.1B-Chat-v1.0` (1.1B, fast)
- `meta-llama/Llama-2-7b-hf` (7B, good quality)
- `mistralai/Mistral-7B-Instruct-v0.1` (7B, fast)
- `NousResearch/Meta-Llama-3-8B-Instruct` (8B, quality)

---

## Testing with Agents

### 1. Start vLLM

```bash
cd model-api/vllm
docker-compose -f docker-compose-simple.yaml up -d
```

### 2. Run agent against vLLM

```bash
# Use the simple TinyLlama model
export MODEL_API_URL=http://localhost:8001/v1
export MODEL_NAME=tinyllama

# Run test
python3 agent/examples/simple-math-agent/agent.py
```

### 3. Check vLLM logs

```bash
cd model-api/vllm
docker-compose logs -f vllm
```

---

## Kubernetes Deployment

### Simple Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-tinyllama
  namespace: agentic-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vllm
  template:
    metadata:
      labels:
        app: vllm
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        ports:
        - containerPort: 8000
        env:
        - name: MODEL_NAME
          value: "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
        - name: SERVED_MODEL_NAME
          value: "tinyllama"
        - name: VLLM_TENSOR_PARALLEL_SIZE
          value: "1"
        - name: VLLM_GPU_MEMORY_UTILIZATION
          value: "0.3"
        args:
        - "--model"
        - "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
        - "--served-model-name"
        - "tinyllama"
        - "--host"
        - "0.0.0.0"
        - "--port"
        - "8000"
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
        # GPU support (optional)
        # resources:
        #   limits:
        #     nvidia.com/gpu: "1"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 60
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 5
        volumeMounts:
        - name: models
          mountPath: /root/.cache/huggingface
      volumes:
      - name: models
        emptyDir: {}
        # For persistent model caching:
        # persistentVolumeClaim:
        #   claimName: vllm-models-pvc

---
apiVersion: v1
kind: Service
metadata:
  name: vllm
  namespace: agentic-system
spec:
  selector:
    app: vllm
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP
```

### Deploy to Kubernetes

```bash
# Apply manifest
kubectl apply -f vllm-deployment.yaml

# Wait for pod startup
kubectl wait --for=condition=ready pod -l app=vllm -n agentic-system --timeout=300s

# Port-forward to test
kubectl port-forward -n agentic-system svc/vllm 8001:8000
```

---

## GPU Support

### Local Docker Compose (with GPU)

Requirements:
- NVIDIA GPU
- nvidia-docker installed
- NVIDIA Container Runtime

```bash
# Edit docker-compose.yaml
# Uncomment the deploy.resources section:

  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

Then start:
```bash
docker-compose up -d
```

### Kubernetes with GPU

Update the K8s manifest:

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

Ensure your K8s cluster has:
- NVIDIA device plugin installed
- GPU nodes available
- NVIDIA Container Runtime configured

---

## Comparison: vLLM vs LiteLLM

| Aspect | vLLM (Hosted) | LiteLLM (Proxy) |
|--------|--------------|-----------------|
| **Model source** | In-cluster | External Ollama |
| **Model management** | Self-contained | Shared |
| **Scaling** | Easy (Deployment replicas) | Dependent on Ollama |
| **Best for** | Production K8s | Development |
| **Setup complexity** | Medium | Simple |
| **Model download time** | First startup | N/A (uses Ollama) |
| **GPU support** | Native | Through Ollama |

---

## Troubleshooting

### vLLM won't start

```bash
# Check logs
docker-compose logs vllm

# Common issues:
# 1. Model too large for available memory
#    → Use TinyLlama or smaller model
# 2. Port 8001 already in use
#    → Change port in docker-compose.yaml
# 3. HuggingFace model download fails
#    → Check internet connection
#    → Try different model
```

### Agent can't connect to vLLM

```bash
# Test vLLM directly
curl http://localhost:8001/models

# Check if it's returning models
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"tinyllama",
    "messages":[{"role":"user","content":"test"}],
    "max_tokens":50
  }'
```

### Model download stuck

```bash
# vLLM downloads models to:
# ~/.cache/huggingface/

# To pre-download model:
docker run -it \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  python -c "from transformers import AutoTokenizer; \
    AutoTokenizer.from_pretrained('TinyLlama/TinyLlama-1.1B-Chat-v1.0')"
```

### Memory issues

**TinyLlama**: ~2-3GB RAM
**Llama-2-7B**: ~14-16GB RAM

If OOM:
1. Use smaller model
2. Reduce batch size
3. Add swap space
4. Use GPU with VRAM

---

## Next Steps

1. **Test locally** → Run docker-compose-simple.yaml
2. **Test with agents** → Point agents to vLLM
3. **Deploy to K8s** → Use operator to manage vLLM as ModelAPI resource
4. **Optimize** → Scale replicas, tune parameters

---

## Files in This Directory

- `docker-compose.yaml` - Full setup with Llama-2-7B
- `docker-compose-simple.yaml` - CPU-friendly with TinyLlama
- `README.md` - This file
