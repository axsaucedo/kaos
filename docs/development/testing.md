# Testing Guide

How to run and write tests for the KAOS.

## Test Structure

```
data-plane/pai-server/tests/   # Python framework tests (96+ tests)
├── conftest.py                # Pytest fixtures
├── helpers.py                 # Test helpers (make_test_server)
├── test_agent.py              # Agent class tests
├── test_agent_server.py       # Server endpoint tests
├── test_agentic_loop.py       # Agentic loop tests
├── test_string_mode.py        # String-mode tool calling tests
└── test_telemetry.py          # OpenTelemetry tests

operator/controllers/integration/  # Go integration tests (8 tests with envtest)
├── suite_test.go               # Test suite setup with envtest
└── controller_test.go          # Controller integration tests

operator/tests/e2e/         # Kubernetes E2E tests (14 tests)
├── conftest.py             # K8s fixtures
├── test_agentic_loop_e2e.py    # Agentic loop E2E
├── test_base_func_e2e.py       # Basic functionality
├── test_modelapi_e2e.py        # ModelAPI tests
└── test_multi_agent_e2e.py     # Multi-agent tests
```

## Running All Tests

```bash
# Python tests
cd data-plane/pai-server && source .venv/bin/activate && python -m pytest tests/ -v

# Go integration tests
cd operator && make test

# E2E tests (parallel by default)
cd operator/tests && source .venv/bin/activate && make test
```

## Running Python Tests

```bash
cd data-plane/pai-server
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

## Running Go Integration Tests

The Go integration tests use `envtest` to run controllers against a real API server.

```bash
cd operator

# Run all Go tests (installs envtest if needed)
make test

# Clean and rebuild
make clean && make test
```

### What the tests verify:
- **ModelAPI Controller**: Deployment, Service, ConfigMap creation for Proxy/Hosted modes
- **MCPServer Controller**: Deployment with MCP_TOOLS_STRING env var, fromPackage handling
- **Agent Controller**: Env vars (AGENT_NAME, PEER_AGENTS), podSpec merging, Service creation

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
kubectl get pods -n kaos-system
```

### Run Tests

```bash
# Run all E2E tests in parallel (default, ~2 min)
make test

# Run sequentially (~6 min, better for debugging)
make test-seq

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

For simpler tests, use `DEBUG_MOCK_RESPONSES` environment variable:

```python
async def test_tool_call():
    agent = Agent(name="test", model_api=model_api)
    
    # Mock responses: tool call -> no-action -> final
    mocks = [
        '{"tool_calls": [{"id": "call_1", "name": "add", "arguments": {"a": 1, "b": 2}}]}',
        'The result is 3.'
    ]
    
    async for response in agent.process_message("Add 1+2"):
        print(response)
```

### Testing Agentic Loop

```python
import pytest
from tests.helpers import make_test_server

@pytest.fixture
def server():
    return make_test_server(
        mock_responses=["Hello!"],
        agent_name="test-agent",
    )

async def test_basic_response(server):
    """Use DEBUG_MOCK_RESPONSES for deterministic testing."""
    from httpx import AsyncClient
    async with AsyncClient(app=server.app, base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={
            "model": "test",
            "messages": [{"role": "user", "content": "Hello"}],
        })
        assert response.status_code == 200
        assert "Hello!" in response.json()["choices"][0]["message"]["content"]
```

### Testing Memory Events

```python
async def test_memory_events(server):
    from httpx import AsyncClient
    async with AsyncClient(app=server.app, base_url="http://test") as client:
        await client.post("/v1/chat/completions", json={
            "model": "test",
            "messages": [{"role": "user", "content": "Hello"}],
        })

        # Verify sessions
        sessions = await client.get("/memory/sessions")
        session_list = sessions.json()["sessions"]
        assert len(session_list) > 0

        # Verify events
        sid = session_list[0]
        events = await client.get(f"/memory/events?session_id={sid}")
        event_types = [e["event_type"] for e in events.json()["events"]]
        assert "user_message" in event_types
        assert "agent_response" in event_types
```

### Testing HTTP Endpoints

```python
import pytest
from httpx import AsyncClient
from pai_server.server import create_agent_server

@pytest.fixture
async def test_client():
    server = create_agent_server()
    async with AsyncClient(app=server.app, base_url="http://test") as client:
        yield client

async def test_health_endpoint(test_client):
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

async def test_agent_card(test_client):
    response = await test_client.get("/.well-known/agent.json")
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
apiVersion: kaos.tools/v1alpha1
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

### GitHub Actions E2E Tests

The project includes a GitHub Actions workflow that runs E2E tests in an isolated KIND cluster. See `.github/workflows/e2e-tests.yaml`.

The workflow:
1. Creates a KIND cluster with a local Docker registry
2. Installs Gateway API CRDs and Envoy Gateway
3. Builds and pushes operator/agent images to the local registry
4. Runs the full E2E test suite

### Local KIND Testing

You can run the same E2E tests locally using KIND:

```bash
# Create KIND cluster with Gateway API, MetalLB, and registry (one-time setup)
make kind-create

# Run E2E tests in KIND (builds images, installs operator, runs tests)
make kind-e2e-run-tests

# Delete KIND cluster when done
make kind-delete
```

The `kind-create` target:
1. Creates KIND cluster with local Docker registry
2. Installs Gateway API CRDs and Envoy Gateway
3. Creates the GatewayClass for Envoy Gateway
4. Installs MetalLB for LoadBalancer support

The `kind-e2e-run-tests` target:
1. Builds all Docker images (including pulling external LiteLLM/Ollama images)
2. Pushes images to the local KIND registry (localhost:5001)
3. Installs the KAOS operator via Helm
4. Sets up port-forwarding to the Gateway for host access
5. Runs all 14 E2E tests in parallel

**Note:** On macOS, the script uses `kubectl port-forward` because Docker's bridge
network is not directly accessible from the host. The tests use port 8888 locally.

### Custom Helm Values for CI

The E2E tests support a `HELM_VALUES_FILE` environment variable to override default Helm values:

```bash
# Create custom values file
cat > /tmp/my-values.yaml << EOF
controllerManager:
  manager:
    image:
      repository: my-registry/kaos-operator
      tag: v1.0.0
    imagePullPolicy: Always
defaultImages:
  agentRuntime: my-registry/kaos-agent:v1.0.0
  mcpServer: my-registry/kaos-mcp-server:v1.0.0
EOF

# Run tests with custom values
cd operator/tests
HELM_VALUES_FILE=/tmp/my-values.yaml make test
```

### Python Unit Tests GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  python-tests:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.12'
    - name: Install dependencies
      run: |
        cd data-plane/pai-server
        pip install -e ".[dev]"
    - name: Run tests
      run: |
        cd data-plane/pai-server
        pytest tests/ -v
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
