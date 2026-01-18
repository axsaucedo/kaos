"""Pytest configuration and fixtures for E2E tests.

Uses Gateway API for routing - all requests go through the kaos-gateway.
"""

import asyncio
import os
import time
import subprocess
import tempfile
import fcntl
from typing import Dict, Any, Generator

import pytest
import httpx
from sh import kubectl, helm, ErrorReturnCode
import yaml


# Gateway configuration - can be overridden via environment variable for KIND clusters
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:80")
CHART_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../chart"))
RELEASE_NAME = "kaos"
OPERATOR_NAMESPACE = "kaos-system"
LOCK_FILE = os.path.join(tempfile.gettempdir(), "kaos-operator.lock")


async def async_wait_for_healthy(
    url: str, max_retries: int = 10, delay: float = 1.0
) -> httpx.Response:
    """Async helper to wait for a resource to be healthy with retries.

    This handles transient 503s from the gateway during routing updates.
    Adds a small stabilization delay after first success to handle flapping.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(max_retries):
            try:
                response = await client.get(f"{url}/health")
                if response.status_code == 200:
                    # Brief stabilization delay to handle gateway flapping
                    await asyncio.sleep(0.5)
                    return response
            except Exception:
                pass
            if i < max_retries - 1:
                await asyncio.sleep(delay)
        # Final attempt - let it raise if it fails
        return await client.get(f"{url}/health")


def gateway_url(namespace: str, resource_type: str, resource_name: str) -> str:
    """Get the Gateway URL for a resource.

    Args:
        namespace: Kubernetes namespace
        resource_type: One of 'agent', 'modelapi', 'mcp'
        resource_name: Name of the resource

    Returns:
        Full Gateway URL for the resource
    """
    return f"{GATEWAY_URL}/{namespace}/{resource_type}/{resource_name}"


def create_custom_resource(body: Dict[str, Any], namespace: str):
    """Create a custom resource using kubectl apply."""
    yaml_content = yaml.dump(body)
    kubectl("apply", "-f", "-", "-n", namespace, _in=yaml_content)


def wait_for_deployment(namespace: str, name: str, timeout: int = 300):
    """Wait for deployment to exist and be ready."""
    start_time = time.time()

    # Poll for deployment existence first
    while time.time() - start_time < timeout:
        try:
            result = kubectl(
                "get",
                "deployment",
                name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.metadata.name}",
                _ok_code=[0, 1],
            )
            if name in str(result):
                break
        except Exception:
            pass
        time.sleep(1)

    # Wait for rollout
    remaining_timeout = max(10, timeout - int(time.time() - start_time))
    kubectl(
        "rollout",
        "status",
        f"deployment/{name}",
        "-n",
        namespace,
        "--timeout",
        f"{remaining_timeout}s",
    )


def wait_for_resource_ready(
    url: str, max_wait: int = 30, health_path: str = "/health"
) -> bool:
    """Wait for a resource to be accessible via Gateway.

    Args:
        url: Base URL of the resource
        max_wait: Maximum seconds to wait
        health_path: Health endpoint path (default: /health)
            For LiteLLM ModelAPI, use /health/liveliness for faster response
    """
    for _ in range(max_wait * 4):
        try:
            response = httpx.get(f"{url}{health_path}", timeout=2.0)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"Resource not ready at {url} after {max_wait}s")


def _install_operator():
    """Install operator with Gateway API enabled via Helm.

    Uses file locking to ensure only one xdist worker installs.
    """
    # Use file lock to coordinate across xdist workers
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Check if already installed (by another worker)
        try:
            result = kubectl(
                "get",
                "deployment",
                "-n",
                OPERATOR_NAMESPACE,
                "-l",
                f"app.kubernetes.io/instance={RELEASE_NAME}",
                "-o",
                "jsonpath={.items[0].metadata.name}",
                _ok_code=[0, 1],
            )
            if "controller-manager" in str(result):
                # Already installed, just wait for Gateway
                for _ in range(30):
                    try:
                        result = kubectl(
                            "get",
                            "gateway",
                            "kaos-gateway",
                            "-n",
                            OPERATOR_NAMESPACE,
                            "-o",
                            "jsonpath={.status.conditions[?(@.type=='Programmed')].status}",
                        )
                        if "True" in str(result):
                            return
                    except Exception:
                        pass
                    time.sleep(1)
                return
        except Exception:
            pass

        # Create namespace
        try:
            kubectl("create", "namespace", OPERATOR_NAMESPACE)
        except ErrorReturnCode:
            pass

        # Install CRDs with server-side apply
        crd_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../config/crd/bases")
        )
        kubectl("apply", "--server-side", "-f", crd_path)

        # Install operator with Gateway API enabled
        helm_args = [
            "upgrade",
            "--install",
            RELEASE_NAME,
            CHART_PATH,
            "--namespace",
            OPERATOR_NAMESPACE,
        ]
        # Support custom values file for CI (e.g., KIND registry images)
        # Values file must come before --set flags so --set can override if needed
        values_file = os.environ.get("HELM_VALUES_FILE")
        if values_file and os.path.exists(values_file):
            helm_args.extend(["-f", values_file])
        else:
            # Default to local images for Docker Desktop
            helm_args.extend(
                [
                    "--set",
                    "controllerManager.manager.image.repository=kaos-operator",
                    "--set",
                    "controllerManager.manager.image.tag=latest",
                ]
            )
        helm_args.extend(
            [
                "--set",
                "gatewayAPI.enabled=true",
                "--set",
                "gatewayAPI.createGateway=true",
                "--set",
                "gatewayAPI.gatewayClassName=envoy-gateway",
                "--skip-crds",
                "--wait",
                "--timeout",
                "120s",
            ]
        )
        helm(*helm_args)

        # Wait for Gateway to be ready
        for _ in range(30):
            try:
                result = kubectl(
                    "get",
                    "gateway",
                    "kaos-gateway",
                    "-n",
                    OPERATOR_NAMESPACE,
                    "-o",
                    "jsonpath={.status.conditions[?(@.type=='Programmed')].status}",
                )
                if "True" in str(result):
                    return
            except Exception:
                pass
            time.sleep(1)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _uninstall_operator():
    """Uninstall operator - called only when all workers are done.

    Note: With xdist parallel execution or when operator is managed externally
    (e.g., by run-e2e-tests.sh), we skip the uninstall.
    """
    # Skip if operator lifecycle is managed externally (e.g., KIND E2E script)
    if os.environ.get("OPERATOR_MANAGED_EXTERNALLY"):
        return

    # Only uninstall if running without xdist (single worker)
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return  # Skip cleanup in parallel mode

    try:
        helm("uninstall", RELEASE_NAME, "-n", OPERATOR_NAMESPACE, _ok_code=[0, 1])
    except Exception:
        pass
    try:
        kubectl(
            "delete", "namespace", OPERATOR_NAMESPACE, "--wait=false", _ok_code=[0, 1]
        )
    except Exception:
        pass


@pytest.fixture(scope="session")
def gateway_setup():
    """Session-scoped fixture that installs operator with Gateway API.

    This runs once per test session and ensures:
    1. Operator is installed with Gateway API enabled
    2. Gateway is ready to accept routes
    3. Cleanup happens at end of session
    """
    _install_operator()
    yield GATEWAY_URL
    _uninstall_operator()


@pytest.fixture(scope="module")
def shared_namespace(request, gateway_setup) -> Generator[str, None, None]:
    """Module-scoped fixture that creates a test namespace."""
    import re

    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
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
    """Module-scoped ModelAPI for tests that use mock_response."""
    name = "shared-mock-proxy"
    modelapi_spec = create_modelapi_resource(shared_namespace, name)
    create_custom_resource(modelapi_spec, shared_namespace)
    wait_for_deployment(shared_namespace, f"modelapi-{name}", timeout=120)

    # Wait for HTTPRoute to be ready
    url = gateway_url(shared_namespace, "modelapi", name)
    wait_for_resource_ready(url, max_wait=30)
    yield name


def create_modelapi_resource(
    namespace: str, name: str = "mock-proxy"
) -> Dict[str, Any]:
    """Create a ModelAPI resource spec for LiteLLM proxy (supports mock_response)."""
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                "model": "gpt-3.5-turbo",
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                    {"name": "LITELLM_LOG", "value": "WARN"},
                ],
            },
        },
    }


def create_modelapi_hosted_resource(
    namespace: str, name: str = "ollama-hosted"
) -> Dict[str, Any]:
    """Create a ModelAPI resource spec for Hosted mode with in-cluster Ollama.

    This runs Ollama inside the cluster with the smollm2:135m model.
    The model is pulled via an init container.
    """
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "mode": "Hosted",
            "hostedConfig": {
                "model": "smollm2:135m",
                "env": [
                    {"name": "OLLAMA_DEBUG", "value": "false"},
                ],
            },
        },
    }


def create_modelapi_proxy_ollama_resource(
    namespace: str, name: str = "ollama-proxy"
) -> Dict[str, Any]:
    """Create a ModelAPI resource spec for Proxy mode with host Ollama backend.

    This connects to Ollama running on the host machine via host.docker.internal.
    Only works in Docker Desktop, NOT in KIND/CI.
    """
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                "apiBase": "http://host.docker.internal:11434",
                "model": "ollama/smollm2:135m",
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                    {"name": "LITELLM_LOG", "value": "WARN"},
                ],
            },
        },
    }


def create_mcpserver_resource(
    namespace: str, name: str = "echo-server"
) -> Dict[str, Any]:
    """Create an MCPServer resource for test-mcp-echo-server."""
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "type": "python-runtime",
            "config": {
                "tools": {"fromPackage": "test-mcp-echo-server"},
                "env": [{"name": "LOG_LEVEL", "value": "INFO"}],
            },
        },
    }


def create_agent_resource(
    namespace: str,
    modelapi_name: str,
    mcpserver_names: list,
    agent_name: str = "echo-agent",
    sub_agents: list = None,
    reasoning_loop_max_steps: int = None,
    model_name: str = "ollama/smollm2:135m",
) -> Dict[str, Any]:
    """Create an Agent resource.

    Args:
        model_name: Model name to use. For Proxy mode, use 'ollama/smollm2:135m'.
                   For Hosted mode (direct Ollama), use 'smollm2:135m'.
    """
    config = {
        "description": "E2E test echo agent",
        "instructions": "You are a helpful test assistant.",
        "env": [
            {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
            {"name": "MODEL_NAME", "value": model_name},
        ],
    }

    if reasoning_loop_max_steps is not None:
        config["reasoningLoopMaxSteps"] = reasoning_loop_max_steps

    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "Agent",
        "metadata": {"name": agent_name, "namespace": namespace},
        "spec": {
            "modelAPI": modelapi_name,
            "mcpServers": mcpserver_names,
            "config": config,
            "agentNetwork": {"access": sub_agents or []},
        },
    }


# Legacy port-forward helpers for tests that need direct service access
def get_next_port() -> int:
    """Get next available port for port-forwarding."""
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    base = 18000 + (
        int(worker_id.replace("gw", "0").replace("main", "0").replace("master", "0"))
        * 100
    )
    if not hasattr(get_next_port, "_counters"):
        get_next_port._counters = {}
    if worker_id not in get_next_port._counters:
        get_next_port._counters[worker_id] = base
    port = get_next_port._counters[worker_id]
    get_next_port._counters[worker_id] += 1
    return port


def port_forward(
    namespace: str, service_name: str, local_port: int, remote_port: int = 8000
) -> subprocess.Popen:
    """Start port-forward to a service (legacy, prefer Gateway)."""
    return subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{service_name}",
            f"{local_port}:{remote_port}",
            "-n",
            namespace,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def port_forward_with_wait(
    namespace: str, service_name: str, local_port: int, remote_port: int = 8000
) -> subprocess.Popen:
    """Start port-forward and wait for service to be ready (legacy)."""
    process = port_forward(namespace, service_name, local_port, remote_port)
    time.sleep(0.5)
    for _ in range(40):
        try:
            response = httpx.get(f"http://localhost:{local_port}/health", timeout=2.0)
            if response.status_code == 200:
                return process
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"Service not ready after 10s")
