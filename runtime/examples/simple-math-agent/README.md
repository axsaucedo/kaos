# Simple Math Agent - End-to-End Test

This example tests the actual `runtime/server/server.py` by:
- Starting it as a subprocess via uvicorn
- Configuring it entirely via environment variables
- Making HTTP requests to test agent endpoints
- Verifying model API and MCP tool integration

This is an **end-to-end test of production code** that exactly mimics what happens in Kubernetes.

## Prerequisites

1. **Local Ollama Server** running with SmolLM2 model:
   ```bash
   ollama pull smollm2:135m  # HuggingFaceTB/SmolLM2-135M-Instruct
   ollama serve
   ```

2. **MCP Server** (calculator) running:
   ```bash
   pip install mcp-server-calculator
   uvx mcp-server-calculator
   ```

3. **Python 3.11+** with required dependencies:
   ```bash
   pip install httpx fastapi uvicorn
   ```

## Setup

1. Copy environment configuration:
   ```bash
   make setup
   ```

2. Optional: Edit `.env` to customize:
   ```
   MODEL_API_URL=http://localhost:11434/v1
   MODEL_NAME=smollm2:135m
   MCP_SERVER_MATH_TOOLS_URL=http://localhost:8001
   ```

## Running the Test

```bash
make run
```

Or directly:
```bash
python3 agent.py
```

## What This Test Does

1. **Starts server.py**: Spawns `runtime/server/server.py` on port 8000 via uvicorn
2. **Waits for readiness**: Polls `/ready` endpoint until server responds
3. **Gets Agent Card**: Retrieves agent capabilities via `/agent/card` (A2A discovery)
4. **Invokes agent**: Sends a math task to `/agent/invoke` endpoint
5. **Prints response**: Displays the model's reasoning and answer
6. **Cleans up**: Terminates the server process

## Expected Output

```
============================================================
Simple Math Agent - End-to-End Test
============================================================

Test 1: Agent Card Discovery
----------------------------------------
2025-12-26 10:30:45 - agent - INFO - Agent card: math-agent
2025-12-26 10:30:45 - agent - INFO -   Description: A simple mathematical reasoning agent
2025-12-26 10:30:45 - agent - INFO -   Tools: 1 available
2025-12-26 10:30:45 - agent - INFO -   Capabilities: {'model_reasoning': True, 'tool_use': True, 'agent_to_agent': False}

Test 2: Math Reasoning Task
----------------------------------------
2025-12-26 10:30:46 - agent - INFO - Invoking agent with task: Calculate: What is 234 + 567 - 89?...
2025-12-26 10:30:50 - agent - INFO - Model response received (350 chars)

============================================================
Let me work through this calculation step by step.

First: 234 + 567 = 801
Then: 801 - 89 = 712

Therefore, 234 + 567 - 89 = 712
============================================================
```

## Troubleshooting

### "Connection refused" errors
- Ensure Ollama is running: `ollama serve`
- Ensure model is available: `ollama pull smollm2:135m`
- Ensure MCP calculator is running: `uvx mcp-server-calculator`

### "Server did not become ready in time"
- Check Ollama connectivity: `curl http://localhost:11434/api/tags`
- Check if port 8000 is already in use: `lsof -i :8000`
- Review server logs for startup errors

### "Failed to get agent response"
- Verify model is loaded: `ollama list`
- Check Ollama model API: `curl -X POST http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"smollm2:135m","messages":[{"role":"user","content":"test"}]}'`

## Kubernetes Equivalent

This test uses the exact same `runtime/server/server.py` that runs in Kubernetes:

| Local | Kubernetes |
|-------|-----------|
| Python subprocess + uvicorn | Pod with `python -m uvicorn server:app` |
| Environment variables in dict | Pod environment variables from Deployment |
| localhost:8000 | Service endpoint `agent-math-agent.default.svc.cluster.local` |
| Subprocess stdout/stderr | Pod logs via `kubectl logs` |
| Cleanup with terminate() | Pod lifecycle managed by ReplicaSet |

## Success Criteria

This test successfully validates that:
- ✅ Server starts with environment variable configuration
- ✅ Agent Card endpoint works (A2A discovery)
- ✅ Model API connectivity established (Ollama)
- ✅ MCP tool loading works
- ✅ Agent reasoning completes successfully
- ✅ HTTP endpoints respond correctly

## Next Steps

This local baseline validates the core runtime before Kubernetes:
- Single agent reasoning with tools ✅
- Model API integration ✅
- MCP tool loading ✅

For multi-agent coordination, see:
- `../multi-agent-coordination/` - Multiple agents with A2A communication

For Kubernetes deployment, see:
- `../../operator/config/samples/agent_example.yaml` - K8s manifest
- `../../tests/e2e_k8s_test.py` - K8s end-to-end tests
