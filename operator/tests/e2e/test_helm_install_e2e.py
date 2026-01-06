"""E2E tests for Helm chart installation."""

import os
import time
import pytest
from sh import kubectl, helm, ErrorReturnCode


# Get absolute path to chart directory
CHART_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../chart"))
RELEASE_NAME = "agentic-test"


@pytest.fixture(scope="module")
def helm_namespace():
    """Create a namespace for Helm installation test."""
    import os
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
    namespace = f"helm-test-{worker_id}-{int(time.time()) % 10000}"
    kubectl("create", "namespace", namespace)
    yield namespace
    # Cleanup
    try:
        helm("uninstall", RELEASE_NAME, "-n", namespace, _ok_code=[0, 1])
    except Exception:
        pass
    try:
        kubectl("delete", "namespace", namespace, "--wait=false")
    except Exception:
        pass


def test_helm_install_and_operator_ready(helm_namespace: str):
    """Test that Helm chart installs successfully and operator becomes ready."""
    # Install chart, skipping CRDs if they already exist (e.g., from kustomize)
    helm(
        "install", RELEASE_NAME, CHART_PATH,
        "-n", helm_namespace,
        "--set", "controllerManager.manager.image.repository=agentic-operator",
        "--set", "controllerManager.manager.image.tag=latest",
        "--skip-crds",  # Skip CRDs as they may exist from kustomize install
        "--wait", "--timeout", "120s"
    )
    
    # Verify deployment exists and is ready
    result = kubectl(
        "get", "deployment", "-n", helm_namespace,
        "-l", f"app.kubernetes.io/instance={RELEASE_NAME}",
        "-o", "jsonpath={.items[0].status.readyReplicas}"
    )
    assert str(result).strip() == "1", f"Expected 1 ready replica, got: {result}"
    
    # Verify CRDs are installed
    crds = kubectl("get", "crd", "-o", "name")
    assert "agents.ethical.institute" in str(crds)
    assert "modelapis.ethical.institute" in str(crds)
    assert "mcpservers.ethical.institute" in str(crds)


def test_helm_template_renders():
    """Test that helm template renders without errors."""
    # This test doesn't need a cluster, just validates chart syntax
    result = helm("template", "test-render", CHART_PATH)
    output = str(result)
    
    # Verify key resources are rendered (CRDs are in crds/ dir, not templates)
    assert "kind: Deployment" in output
    assert "kind: ServiceAccount" in output
    assert "kind: ClusterRole" in output


def test_helm_values_override():
    """Test that values can be overridden correctly."""
    result = helm(
        "template", "test-override", CHART_PATH,
        "--set", "controllerManager.replicas=3",
        "--set", "controllerManager.manager.image.tag=v1.0.0"
    )
    output = str(result)
    
    assert "replicas: 3" in output
    assert "agentic-operator:v1.0.0" in output
