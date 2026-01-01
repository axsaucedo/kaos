"""Pytest configuration and fixtures for E2E tests."""

import time
import sys
import subprocess
import concurrent.futures
from typing import Dict, Any, Generator, List, Tuple

import pytest
import httpx
from sh import kubectl
import yaml


# Port allocation - use worker-specific ranges for xdist
def _get_worker_port_base() -> int:
    """Get base port for current worker (supports pytest-xdist)."""
    import os
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    # Extract worker number (gw0 -> 0, gw1 -> 1, etc.)
    try:
        worker_num = int(worker_id.replace("gw", ""))
    except ValueError:
        worker_num = 0
    # Each worker gets 100 ports starting at 18000 + (worker_num * 100)
    return 18000 + (worker_num * 100)


_port_counters: dict = {}


def get_next_port() -> int:
    """Get next available port for port-forwarding (worker-safe)."""
    import os
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker_id not in _port_counters:
        _port_counters[worker_id] = _get_worker_port_base()
    port = _port_counters[worker_id]
    _port_counters[worker_id] += 1
    return port


def create_custom_resource(body: Dict[str, Any], namespace: str):
    """Create a custom resource using kubectl apply."""
    yaml_content = yaml.dump(body)
    kubectl("apply", "-f", "-", "-n", namespace, _in=yaml_content)


def wait_for_deployment(namespace: str, name: str, timeout: int = 300):
    """Wait for deployment to exist and be ready.
    
    First polls for the deployment to exist (operator may take time to create it),
    then waits for the rollout to complete.
    """
    import time
    start_time = time.time()
    
    # Poll for deployment existence first (operator may take time to create it)
    while time.time() - start_time < timeout:
        try:
            # Check if deployment exists
            result = kubectl("get", "deployment", name, "-n", namespace, 
                           "-o", "jsonpath={.metadata.name}", _ok_code=[0, 1])
            if name in str(result):
                break
        except Exception:
            pass
        time.sleep(1)
    
    # Now wait for rollout
    remaining_timeout = max(10, timeout - int(time.time() - start_time))
    kubectl("rollout", "status", f"deployment/{name}", "-n", namespace, 
            "--timeout", f"{remaining_timeout}s")


def port_forward(namespace: str, service_name: str, local_port: int, remote_port: int = 8000) -> subprocess.Popen:
    """Start port-forward to a service."""
    process = subprocess.Popen(
        ["kubectl", "port-forward", f"svc/{service_name}", f"{local_port}:{remote_port}", "-n", namespace],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process


def wait_for_service_ready(url: str, max_wait: int = 10) -> bool:
    """Wait for service to be ready by polling health endpoint."""
    for _ in range(max_wait * 4):  # Check every 0.25s
        try:
            response = httpx.get(f"{url}/health", timeout=2.0)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"Service not ready at {url} after {max_wait}s")


def port_forward_with_wait(namespace: str, service_name: str, local_port: int, 
                           remote_port: int = 8000) -> subprocess.Popen:
    """Start port-forward and wait for service to be ready."""
    process = port_forward(namespace, service_name, local_port, remote_port)
    # Give process time to establish connection
    time.sleep(0.5)
    wait_for_service_ready(f"http://localhost:{local_port}")
    return process


def parallel_port_forwards(namespace: str, 
                           services: List[Tuple[str, int, int]]) -> List[subprocess.Popen]:
    """Start multiple port-forwards in parallel.
    
    Args:
        namespace: Kubernetes namespace
        services: List of (service_name, local_port, remote_port) tuples
    
    Returns:
        List of Popen processes
    """
    processes = []
    # Start all port-forwards
    for service_name, local_port, remote_port in services:
        pf = port_forward(namespace, service_name, local_port, remote_port)
        processes.append((pf, f"http://localhost:{local_port}"))
    
    # Wait briefly for processes to start
    time.sleep(0.5)
    
    # Wait for all services to be ready in parallel
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(wait_for_service_ready, url) for _, url in processes]
        concurrent.futures.wait(futures)
    
    return [pf for pf, _ in processes]


@pytest.fixture(scope="module")
def shared_namespace(request) -> Generator[str, None, None]:
    """Module-scoped fixture that creates a test namespace.
    
    For pytest-xdist parallel execution, each worker gets its own namespace
    to avoid conflicts. Using module scope ensures proper isolation per test file.
    """
    import os
    import re
    # Get worker id for xdist parallel execution
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
    # Include module name for uniqueness (sanitize for K8s naming)
    module_name = request.module.__name__.split(".")[-1]
    module_name = re.sub(r"[^a-z0-9]", "", module_name.lower())[:8]
    namespace = f"e2e-{worker_id}-{module_name}-{int(time.time()) % 10000}"
    kubectl("create", "namespace", namespace)
    yield namespace
    try:
        kubectl("delete", "namespace", namespace, "--wait=false")
    except Exception:
        pass


@pytest.fixture
def test_namespace(shared_namespace: str) -> Generator[str, None, None]:
    """Fixture that provides the shared namespace for tests."""
    yield shared_namespace


@pytest.fixture(scope="module")
def shared_modelapi(shared_namespace: str) -> Generator[str, None, None]:
    """Module-scoped ModelAPI for tests that use mock_response.
    
    Deploys a single LiteLLM proxy that all mock-based tests in the module can share.
    Tests requiring specific ModelAPI configurations should create their own.
    """
    name = "shared-mock-proxy"
    modelapi_spec = create_modelapi_resource(shared_namespace, name)
    create_custom_resource(modelapi_spec, shared_namespace)
    wait_for_deployment(shared_namespace, f"modelapi-{name}", timeout=120)
    yield name


def create_modelapi_resource(namespace: str, name: str = "mock-proxy") -> Dict[str, Any]:
    """Create a ModelAPI resource spec for LiteLLM proxy (supports mock_response).

    This creates a LiteLLM proxy that can be used with mock_response for
    deterministic testing without requiring a real LLM backend.

    Args:
        namespace: Namespace for the resource
        name: Resource name

    Returns:
        Resource specification
    """
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                # Simple CLI mode - LiteLLM will accept any model with mock_response
                "model": "gpt-3.5-turbo",  # Any model name works with mock_response
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                    {"name": "LITELLM_LOG", "value": "WARN"},
                ]
            },
        },
    }


def create_modelapi_hosted_resource(namespace: str, name: str = "ollama-hosted") -> Dict[str, Any]:
    """Create a ModelAPI resource spec for Proxy mode with Ollama backend.

    This creates a LiteLLM proxy to Ollama for tests that need actual model inference.

    Args:
        namespace: Namespace for the resource
        name: Resource name

    Returns:
        Resource specification
    """
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                "apiBase": "http://host.docker.internal:11434",
                "model": "ollama/smollm2:135m",
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                    {"name": "LITELLM_LOG", "value": "WARN"},
                ]
            },
        },
    }


def create_mcpserver_resource(namespace: str, name: str = "echo-server") -> Dict[str, Any]:
    """Create an MCPServer resource for test-mcp-echo-server.

    Args:
        namespace: Namespace for the resource
        name: Resource name

    Returns:
        Resource specification
    """
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "MCPServer",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "spec": {
            "type": "python-runtime",
            "config": {
                "tools": {
                    "fromPackage": "test-mcp-echo-server",
                },
                "env": [
                    {"name": "LOG_LEVEL", "value": "INFO"},
                ],
            },
        },
    }


def create_agent_resource(namespace: str, modelapi_name: str, mcpserver_names: list,
                         agent_name: str = "echo-agent", 
                         sub_agents: list = None,
                         reasoning_loop_max_steps: int = None) -> Dict[str, Any]:
    """Create an Agent resource.

    Args:
        namespace: Namespace for the resource
        modelapi_name: Name of ModelAPI resource to reference
        mcpserver_names: List of MCPServer names to connect to
        agent_name: Agent resource name
        sub_agents: List of sub-agent names for delegation
        reasoning_loop_max_steps: Max reasoning loop steps

    Returns:
        Resource specification
    """
    config = {
        "description": "E2E test echo agent",
        "instructions": "You are a helpful test assistant. You have access to an echo tool for testing.",
        "env": [
            {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
            {"name": "MODEL_NAME", "value": "smollm2:135m"},
        ],
    }
    
    # Add reasoning loop max steps if provided
    if reasoning_loop_max_steps is not None:
        config["reasoningLoopMaxSteps"] = reasoning_loop_max_steps
    
    return {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "Agent",
        "metadata": {
            "name": agent_name,
            "namespace": namespace,
        },
        "spec": {
            "modelAPI": modelapi_name,
            "mcpServers": mcpserver_names,
            "config": config,
            "agentNetwork": {
                "access": sub_agents or [],
            },
        },
    }
