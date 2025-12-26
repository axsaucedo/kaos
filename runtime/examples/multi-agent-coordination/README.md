# Multi-Agent Coordination - End-to-End Test

This example demonstrates Agent-to-Agent (A2A) communication where multiple instances of the actual `runtime/server/server.py` coordinate to solve complex tasks.

**Architecture**:
- **Coordinator Agent** (port 8000): Orchestrates tasks and delegates to specialized agents
- **Researcher Agent** (port 8001): Specialized agent for information gathering and analysis
- **Analyst Agent** (port 8002): Performs calculations using math MCP tools

**Key Features**:
- Each agent is a real runtime/server/server.py instance running via uvicorn
- A2A communication via HTTP endpoints (`/agent/card`, `/agent/invoke`)
- Dynamic agent discovery and peer configuration
- Shared model API (Ollama)
- Specialized tool access (analyst has math MCP tools)

## Prerequisites

1. **Local Ollama Server** with SmolLM2:
   ```bash
   ollama pull smollm2:135m  # HuggingFaceTB/SmolLM2-135M-Instruct
   ollama serve
   ```

2. **MCP Calculator Server** running:
   ```bash
   pip install mcp-server-calculator
   uvx mcp-server-calculator
   # Server listens on port 8003 by default, or set MCP_SERVER_URL env var
   ```

3. **Python 3.11+** with required dependencies:
   ```bash
   pip install httpx
   ```

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│     Shared Model API: Ollama OpenAI-compatible API         │
│     http://localhost:11434/v1 (SmolLM2-135M-Instruct)     │
└─────────────────────────────────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    ┌────▼─────┐       ┌────▼─────┐      ┌────▼─────┐
    │Coordinator│       │ Researcher│      │ Analyst  │
    │8000       │       │ 8001      │      │ 8002     │
    │(no tools) │       │(no tools) │      │(math MCP)│
    └────┬──────┘       └───────────┘      └────┬─────┘
         │                                       │
         │            A2A HTTP Routes            │
         │   /agent/card  /agent/invoke          │
         └───────────────────────────────────────┘
                          │
                ┌─────────▼──────────┐
                │  MCP Math Server   │
                │  localhost:8003    │
                └────────────────────┘
```

Each agent is a separate `runtime/server/server.py` process:
- Loads config entirely from environment variables
- Communicates with peers via HTTP endpoints
- Accesses shared model API
- May have specialized MCP tools

## Setup

1. Copy environment configuration:
   ```bash
   make setup
   ```

2. Optional: Edit `.env` to customize:
   - `MODEL_API_URL`: Ollama endpoint (default: http://localhost:11434/v1)
   - `MODEL_NAME`: Model to use (default: smollm2:135m)
   - `ANALYST_MCP_SERVER_MATH_TOOLS_URL`: MCP calculator endpoint
   - `AGENT_LOG_LEVEL`: Logging level (default: INFO)

## Running the Example

```bash
make run
```

This will:
1. Load configuration from `.env` (auto-created from `.env.example`)
2. Start the Coordinator agent (port 8000, via uvicorn running server.py)
3. Start the Researcher agent (port 8001, via uvicorn running server.py)
4. Start the Analyst agent (port 8002, via uvicorn running server.py)
5. Wait for all agents to be ready
6. Run coordination tests:
   - Test 1: Agent Card Discovery - retrieve capabilities from each agent
   - Test 2: Coordinator delegates math task to Analyst
   - Test 3: Coordinator delegates analysis task to Researcher
7. Stop all agents

## Expected Output

```
============================================================
Multi-Agent Coordination - Setting up agents
============================================================
INFO - Starting all agents...
INFO - Starting coordinator agent on port 8000...
INFO - Starting researcher agent on port 8001...
INFO - Starting analyst agent on port 8002...
INFO - All agents started successfully

============================================================
Running coordination tests
============================================================

Test 1: Agent Card Discovery
--------------------------------------------
INFO - Retrieved card for coordinator: coordinator
INFO - Retrieved card for researcher: researcher
INFO - Retrieved card for analyst: analyst

Test 2: Coordinator → Analyst (Math Task)
--------------------------------------------
INFO - Invoking coordinator with task: Calculate 456 + 789 - 123...
[Agent reasoning and calculation output]

Test 3: Coordinator → Researcher (Analysis Task)
--------------------------------------------
INFO - Invoking coordinator with task: Analyze the capabilities...
[Agent analysis output]

INFO - Cleaning up agents...
```

## Troubleshooting

### "Connection refused" errors
- Ensure Ollama is running: `ollama serve`
- Ensure model is available: `ollama pull smollm2:135m`
- Ensure MCP calculator is running: `uvx mcp-server-calculator`
- Check that ports 8000-8003 are not already in use

### "Agent did not become ready"
- Check Ollama connectivity: `curl http://localhost:11434/api/tags`
- Check server logs for startup errors
- Verify Python dependencies are installed: `pip install httpx fastapi uvicorn`

### "Failed to get agent response"
- Verify model is loaded in Ollama
- Check agent logs for model API errors
- Try a simpler prompt first to verify connectivity

### A2A communication fails
- Verify all agents are running: `lsof -i :8000-8002`
- Check agent readiness: `curl http://localhost:8000/ready`
- Review agent logs for peer agent endpoint issues

## What This Example Tests

This is an **actual end-to-end test** of the production code:

1. **Server Startup**: Verifies `runtime/server/server.py` starts correctly with environment variables
2. **Configuration Loading**: Tests environment variable parsing for agents and MCP servers
3. **Health Checks**: Validates `/health` and `/ready` endpoints
4. **Agent Card Discovery**: Tests A2A agent discovery via `/agent/card`
5. **Task Invocation**: Tests agent reasoning via `/agent/invoke`
6. **Model API Integration**: Verifies Ollama connectivity and inference
7. **MCP Tool Loading**: Tests MCP server integration (analyst only)
8. **Multi-Agent Coordination**: Tests delegating between agents

## Kubernetes Equivalent

This local setup exactly mirrors what happens in Kubernetes:

| Local | Kubernetes |
|-------|-----------|
| Python subprocess with uvicorn | Pod with `python -m uvicorn server:app` |
| Environment variables in dict | Pod environment variables in deployment |
| localhost:8000-8002 | Service DNS: agent-0000.default.svc.cluster.local |
| HTTP health checks | Liveness/Readiness probes |
| Manual port forwarding | Service port mapping |

## Next Steps

This example validates:
- ✅ Local baseline with actual server.py
- ✅ Multi-agent coordination patterns
- ✅ A2A communication via HTTP
- ✅ Environment-based configuration

For Kubernetes deployment, see:
- `../../operator/config/samples/multi_agent_example.yaml` - K8s manifests
- `../../tests/e2e_k8s_test.py` - K8s end-to-end tests

## Performance Notes

- **First invocation**: Slower due to model warming up and token generation
- **Subsequent calls**: Faster as model state persists
- **Network latency**: Minimal on localhost; DNS lookup adds ~1ms in Kubernetes
- **Memory usage**: Each agent process takes ~100-200MB depending on model caching
