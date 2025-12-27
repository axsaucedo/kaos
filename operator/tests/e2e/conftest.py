"""Pytest configuration and fixtures for E2E tests."""

import time
import subprocess
from typing import Dict, Any, Generator

import pytest
from sh import kubectl
import yaml


def create_custom_resource(body: Dict[str, Any], namespace: str):
    """Create a custom resource using kubectl apply."""
    yaml_content = yaml.dump(body)
    kubectl("apply", "-f", "-", "-n", namespace, _in=yaml_content)


def wait_for_deployment(namespace: str, name: str, timeout: int = 300) -> bool:
    """Wait for deployment to be ready."""
    try:
        kubectl("rollout", "status", f"deployment/{name}", "-n", namespace, "--timeout", f"{timeout}s")
        return True
    except Exception:
        return False


def port_forward(namespace: str, service_name: str, local_port: int, remote_port: int = 8000) -> subprocess.Popen:
    """Start port-forward to a service."""
    process = subprocess.Popen(
        ["kubectl", "port-forward", f"svc/{service_name}", f"{local_port}:{remote_port}", "-n", namespace],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    return process


@pytest.fixture
def test_namespace() -> Generator[str, None, None]:
    """Fixture that creates a test namespace and cleans up after test."""
    namespace = f"test-e2e-{int(time.time())}"
    kubectl("create", "namespace", namespace)
    yield namespace
    try:
        kubectl("delete", "namespace", namespace)
    except Exception:
        pass


def create_modelapi_resource(namespace: str, name: str = "ollama-proxy") -> Dict[str, Any]:
    """Create a ModelAPI resource spec for LiteLLM proxy to Ollama.

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
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                    {"name": "LITELLM_LOG", "value": "WARN"},
                    {"name": "LITELLM_MODEL_LIST", "value": "ollama/smollm2:135m"},
                    {"name": "OLLAMA_BASE_URL", "value": "http://host.docker.internal:11434"},
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
                "mcp": "test-mcp-echo-server",
                "env": [
                    {"name": "LOG_LEVEL", "value": "INFO"},
                ],
            },
            "resources": {
                "requests": {"memory": "128Mi", "cpu": "100m"},
                "limits": {"memory": "256Mi", "cpu": "500m"},
            },
        },
    }


def create_agent_resource(namespace: str, modelapi_name: str, mcpserver_names: list,
                         agent_name: str = "echo-agent") -> Dict[str, Any]:
    """Create an Agent resource.

    Args:
        namespace: Namespace for the resource
        modelapi_name: Name of ModelAPI resource to reference
        mcpserver_names: List of MCPServer names to connect to
        agent_name: Agent resource name

    Returns:
        Resource specification
    """
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
            "config": {
                "description": "E2E test echo agent",
                "instructions": "You are a helpful test assistant. You have access to an echo tool for testing.",
                "env": [
                    {"name": "AGENT_LOG_LEVEL", "value": "INFO"},
                    {"name": "MODEL_NAME", "value": "smollm2:135m"},
                ],
            },
            "agentNetwork": {
                "expose": True,
                "access": [],
            },
            "replicas": 1,
            "resources": {
                "requests": {"memory": "256Mi", "cpu": "200m"},
                "limits": {"memory": "512Mi", "cpu": "1000m"},
            },
        },
    }
