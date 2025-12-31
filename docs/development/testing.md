# Testing Guide

How to run and write tests for the Agentic Kubernetes Operator.

## Test Structure

```
python/tests/               # Python framework tests
├── conftest.py             # Pytest fixtures
├── mock_model_server.py    # Mock LLM server for testing
├── test_agent.py           # Agent class tests
├── test_agent_server.py    # Server endpoint tests
├── test_agentic_loop.py    # Agentic loop tests
└── test_mcptools.py        # MCP server/client tests

operator/tests/e2e/         # Kubernetes E2E tests
├── conftest.py             # K8s fixtures
├── test_agentic_loop_e2e.py    # Agentic loop E2E
├── test_base_func_e2e.py       # Basic functionality
├── test_modelapi_e2e.py        # ModelAPI tests
└── test_multi_agent_e2e.py     # Multi-agent tests
```

## Running Python Tests

```bash
cd python
source .venv/bin/activate

# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_agent.py -v

# Run specific test
python -m pytest tests/test_agent.py::test_agent_creation -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

### Test Categories

| File | Description |
|------|-------------|
| `test_agent.py` | Agent creation, configuration, memory |
| `test_agent_server.py` | HTTP endpoints, streaming, delegation |
| `test_agentic_loop.py` | Tool calling, delegation parsing, max steps |
| `test_mcptools.py` | MCP server creation, tool registration, client |

## Running Kubernetes E2E Tests

### Prerequisites

1. Kubernetes cluster running (Docker Desktop, kind, etc.)
2. Operator deployed or running locally
3. Ollama running locally (for model tests)

### Setup

```bash
cd operator/tests
source .venv/bin/activate

# Ensure operator is running
kubectl get pods -n agentic-system
```

### Run Tests

```bash
# Run all E2E tests
python -m pytest e2e/ -v

# Run specific test file
python -m pytest e2e/test_base_func_e2e.py -v

# Run with more output
python -m pytest e2e/ -v -s
```

## Writing Tests

### Mock Model Server

The `mock_model_server.py` provides a FastAPI server that returns deterministic responses:

```python
from tests.mock_model_server import create_mock_server
import asyncio

async def test_with_mock():
    # Create mock that returns specific response
    server = create_mock_server(port=8099)
    
    # Start server in background
    # ... run test ...
    
    # Server will return mock responses
```

### Using mock_response

For simpler tests, use the `mock_response` parameter:

```python
async def test_tool_call():
    agent = Agent(name="test", model_api=model_api)
    
    # Mock response that triggers tool call
    mock = '''I'll use the calculator.

```tool_call
{"tool": "add", "arguments": {"a": 1, "b": 2}}
```'''
    
    async for response in agent.process_message(
        "Add 1+2",
        mock_response=mock
    ):
        print(response)
```

### Testing Agentic Loop

```python
import pytest
from agent.client import Agent, AgenticLoopConfig
from modelapi.client import ModelAPI

@pytest.fixture
def agent():
    model_api = ModelAPI(
        model="test",
        api_base="http://localhost:8099"
    )
    return Agent(
        name="test-agent",
        model_api=model_api,
        loop_config=AgenticLoopConfig(max_steps=3)
    )

async def test_max_steps_reached(agent):
    # Mock that always returns tool call (infinite loop)
    mock = '''```tool_call
{"tool": "echo", "arguments": {"text": "test"}}
```'''
    
    responses = []
    async for chunk in agent.process_message("test", mock_response=mock):
        responses.append(chunk)
    
    # Should hit max steps
    assert "maximum reasoning steps" in "".join(responses).lower()
```

### Testing Memory Events

```python
async def test_memory_events():
    agent = Agent(name="test", model_api=model_api)
    
    # Process a message
    session_id = None
    async for _ in agent.process_message("Hello"):
        pass
    
    # Get session ID from memory
    sessions = await agent.memory.list_sessions()
    session_id = sessions[0]
    
    # Verify events
    events = await agent.memory.get_session_events(session_id)
    
    event_types = [e.event_type for e in events]
    assert "user_message" in event_types
    assert "agent_response" in event_types
```

### Testing HTTP Endpoints

```python
import pytest
from httpx import AsyncClient
from agent.server import AgentServer
from agent.client import Agent

@pytest.fixture
async def test_client():
    agent = Agent(name="test", model_api=model_api)
    server = AgentServer(agent, port=8000)
    
    async with AsyncClient(app=server.app, base_url="http://test") as client:
        yield client

async def test_health_endpoint(test_client):
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

async def test_agent_card(test_client):
    response = await test_client.get("/.well-known/agent")
    assert response.status_code == 200
    card = response.json()
    assert "name" in card
    assert "capabilities" in card
```

### Testing MCP Tools

```python
from mcptools.server import MCPServer, MCPServerSettings
from mcptools.client import MCPClient, MCPClientSettings

async def test_tool_registration():
    settings = MCPServerSettings(mcp_port=8001)
    server = MCPServer(settings)
    
    def echo(text: str) -> str:
        return f"Echo: {text}"
    
    server.register_tools({"echo": echo})
    
    assert "echo" in server.get_registered_tools()

async def test_tool_call():
    # Assuming server is running on port 8001
    settings = MCPClientSettings(
        mcp_client_host="http://localhost",
        mcp_client_port="8001"
    )
    client = MCPClient(settings)
    await client.discover_tools()
    
    result = await client.call_tool("echo", {"text": "hello"})
    assert "hello" in str(result)
```

## E2E Test Patterns

### Creating Test Resources

```python
import subprocess
import time

def create_agent(name, namespace):
    yaml = f"""
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: {name}
  namespace: {namespace}
spec:
  modelAPI: test-model
  config:
    description: "Test agent"
"""
    subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml, text=True)

def wait_for_ready(resource_type, name, namespace, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["kubectl", "get", resource_type, name, "-n", namespace, 
             "-o", "jsonpath={.status.ready}"],
            capture_output=True, text=True
        )
        if result.stdout == "true":
            return True
        time.sleep(5)
    return False
```

### Cleanup

```python
import pytest

@pytest.fixture
def test_namespace():
    namespace = "test-e2e"
    subprocess.run(["kubectl", "create", "namespace", namespace])
    yield namespace
    subprocess.run(["kubectl", "delete", "namespace", namespace])
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  python-tests:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.12'
    - name: Install dependencies
      run: |
        cd python
        pip install -e ".[dev]"
    - name: Run tests
      run: |
        cd python
        pytest tests/ -v

  e2e-tests:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Start kind cluster
      uses: helm/kind-action@v1
    - name: Deploy operator
      run: |
        cd operator
        make deploy
    - name: Run E2E tests
      run: |
        cd operator/tests
        pip install -r requirements.txt
        pytest e2e/ -v
```

## Test Markers

Use pytest markers to categorize tests:

```python
import pytest

@pytest.mark.slow
async def test_with_real_model():
    """Test that requires actual LLM (slow)."""
    pass

@pytest.mark.integration
async def test_multi_component():
    """Test involving multiple components."""
    pass
```

Run by marker:

```bash
pytest tests/ -v -m "not slow"
pytest tests/ -v -m integration
```
