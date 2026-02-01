"""E2E tests for documentation examples.

These tests execute the markdown examples using Jupytext.
The examples in docs/examples/ are designed to be executable
when run through Jupytext's notebook execution.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from sh import kubectl

from e2e.conftest import (
    GATEWAY_URL,
    create_custom_resource,
    create_modelapi_resource,
    gateway_url,
    wait_for_deployment,
    wait_for_resource_ready,
)


# Path to docs/examples relative to repo root
DOCS_EXAMPLES_PATH = Path(__file__).parent.parent.parent.parent / "docs" / "examples"


def run_jupytext(markdown_file: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute a markdown file using Jupytext."""
    result = subprocess.run(
        [
            sys.executable, "-m", "jupytext",
            "--set-kernel", "python3",
            "--execute",
            str(markdown_file),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=DOCS_EXAMPLES_PATH,
    )
    return result


class TestExamplesViaJupytext:
    """Tests that execute documentation examples using Jupytext."""

    def test_custom_mcp_server_example(self):
        """Execute the custom MCP server example.
        
        This example tests:
        - kaos mcp init
        - kaos mcp build
        - Server customization with %%writefile
        """
        example_file = DOCS_EXAMPLES_PATH / "custom-mcp-server.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"


class TestKAOSMonkeyExample:
    """Tests for the KAOS Monkey example - agent that deletes pods."""

    def test_chaos_agent_deletes_pod(self, shared_namespace: str, shared_modelapi: str):
        """Test an agent that deletes a pod using kubernetes MCP runtime.
        
        This validates the KAOS Monkey pattern from docs/examples/kaos-monkey.md.
        """
        namespace = shared_namespace
        modelapi_name = shared_modelapi

        # Create a test pod to delete
        test_pod_spec = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "chaos-test-pod", "namespace": namespace},
            "spec": {
                "containers": [
                    {
                        "name": "nginx",
                        "image": "nginx:alpine",
                    }
                ],
                "restartPolicy": "Never",
            },
        }
        create_custom_resource(test_pod_spec, namespace)
        
        # Wait for pod to be running
        for _ in range(30):
            result = kubectl(
                "get", "pod", "chaos-test-pod", "-n", namespace,
                "-o", "jsonpath={.status.phase}",
                _ok_code=[0, 1],
            )
            if "Running" in str(result):
                break
            time.sleep(1)

        # Create ServiceAccount for kubernetes MCP
        sa_spec = {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": "chaos-sa", "namespace": namespace},
        }
        create_custom_resource(sa_spec, namespace)

        # Create Role with pod management permissions
        role_spec = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": {"name": "chaos-role", "namespace": namespace},
            "rules": [
                {
                    "apiGroups": [""],
                    "resources": ["pods"],
                    "verbs": ["get", "list", "delete"],
                }
            ],
        }
        create_custom_resource(role_spec, namespace)

        # Create RoleBinding
        rb_spec = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": "chaos-binding", "namespace": namespace},
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": "chaos-sa",
                    "namespace": namespace,
                }
            ],
            "roleRef": {
                "kind": "Role",
                "name": "chaos-role",
                "apiGroup": "rbac.authorization.k8s.io",
            },
        }
        create_custom_resource(rb_spec, namespace)

        # Create MCPServer with kubernetes runtime
        mcp_name = "k8s-tools"
        mcp_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "MCPServer",
            "metadata": {"name": mcp_name, "namespace": namespace},
            "spec": {
                "runtime": "kubernetes",
                "serviceAccountName": "chaos-sa",
            },
        }
        create_custom_resource(mcp_spec, namespace)
        wait_for_deployment(namespace, f"mcpserver-{mcp_name}", timeout=120)

        # Create agent with mock responses that will delete the pod
        agent_name = "chaos-monkey"
        mock_responses = [
            f'Listing pods in namespace {namespace}.\n\n```tool_call\n{{"tool": "get_namespaced_pods", "arguments": {{"namespace": "{namespace}"}}}}\n```',
            f'Found chaos-test-pod. Deleting it now.\n\n```tool_call\n{{"tool": "delete_namespaced_pod", "arguments": {{"namespace": "{namespace}", "name": "chaos-test-pod"}}}}\n```',
            "Done! I deleted chaos-test-pod to simulate a failure.",
        ]
        
        agent_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": agent_name, "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "mcpServers": [mcp_name],
                "config": {
                    "instructions": "You are KAOS Monkey, a chaos engineering agent.",
                },
                "container": {
                    "env": [
                        {"name": "DEBUG_MOCK_RESPONSES", "value": json.dumps(mock_responses)}
                    ]
                },
                "agentNetwork": {"expose": True},
            },
        }
        create_custom_resource(agent_spec, namespace)
        wait_for_deployment(namespace, f"agent-{agent_name}", timeout=120)

        # Wait for agent to be accessible
        agent_url = gateway_url(namespace, "agent", agent_name)
        wait_for_resource_ready(agent_url, max_wait=60)

        # Invoke the agent to cause chaos
        response = httpx.post(
            f"{agent_url}/v1/chat/completions",
            json={
                "model": agent_name,
                "messages": [{"role": "user", "content": "Cause some chaos"}],
            },
            timeout=60.0,
        )
        assert response.status_code == 200

        # Verify the pod was deleted
        time.sleep(2)  # Give it a moment
        result = kubectl(
            "get", "pod", "chaos-test-pod", "-n", namespace,
            "-o", "jsonpath={.metadata.name}",
            _ok_code=[0, 1],
        )
        assert "chaos-test-pod" not in str(result), "Pod should have been deleted"


class TestMultiAgentTelemetryExample:
    """Tests for the Multi-Agent Telemetry example."""

    def test_multi_agent_delegation(self, shared_namespace: str, shared_modelapi: str):
        """Test multi-agent delegation with mock responses."""
        namespace = shared_namespace
        modelapi_name = shared_modelapi

        # Create researcher agent
        researcher_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "researcher", "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "config": {
                    "description": "Research specialist",
                    "instructions": "You gather information.",
                },
                "container": {
                    "env": [
                        {
                            "name": "DEBUG_MOCK_RESPONSES",
                            "value": json.dumps(["Research findings: AI adoption is growing 40% YoY."]),
                        }
                    ]
                },
                "agentNetwork": {"expose": True},
            },
        }
        create_custom_resource(researcher_spec, namespace)

        # Create coordinator agent
        coordinator_mock = json.dumps([
            'Let me delegate to the researcher.\n\n```delegate\n{"agent": "researcher", "task": "Research AI trends"}\n```',
            "Based on the research: AI adoption is growing rapidly with 40% YoY growth.",
        ])
        
        coordinator_spec = {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "coordinator", "namespace": namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "test-model",
                "config": {
                    "description": "Coordinator agent",
                    "instructions": "You coordinate with specialist agents.",
                },
                "container": {
                    "env": [
                        {"name": "DEBUG_MOCK_RESPONSES", "value": coordinator_mock}
                    ]
                },
                "agentNetwork": {
                    "expose": True,
                    "access": ["researcher"],
                },
            },
        }
        create_custom_resource(coordinator_spec, namespace)

        # Wait for both agents
        wait_for_deployment(namespace, "agent-researcher", timeout=120)
        wait_for_deployment(namespace, "agent-coordinator", timeout=120)

        researcher_url = gateway_url(namespace, "agent", "researcher")
        coordinator_url = gateway_url(namespace, "agent", "coordinator")
        
        wait_for_resource_ready(researcher_url, max_wait=60)
        wait_for_resource_ready(coordinator_url, max_wait=60)

        # Test coordinator - it should delegate to researcher
        response = httpx.post(
            f"{coordinator_url}/v1/chat/completions",
            json={
                "model": "coordinator",
                "messages": [{"role": "user", "content": "What are the AI trends?"}],
            },
            timeout=60.0,
        )
        assert response.status_code == 200
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        assert "40%" in content or "growing" in content.lower()
