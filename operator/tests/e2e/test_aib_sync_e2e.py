"""End-to-end test for the agent-auth credential path.

Validates the full chain that provisions per-agent identity-broker credentials
and loads them into agent pods:

1. The Go sync service projects KAOS Agents into the identity broker (AIB),
   mints client credentials, and writes a per-agent ``kaos-aib-<agent>`` Secret.
2. The operator mounts that Secret into the agent Deployment as ``AGENT_AUTH_*``
   environment variables and a read-only ``/var/run/aib`` volume.

This test is opt-in: it requires a cluster installed with ``--auth-enabled``
plus the identity broker and sync service (see the ``kind-e2e-aib`` make
target). It is skipped unless ``KAOS_AIB_E2E`` is set so the default E2E suite,
which runs without AIB, is unaffected.
"""

import json
import os
import time

import pytest
from sh import kubectl

from e2e.conftest import (
    create_custom_resource,
    create_modelapi_resource,
    create_agent_resource,
    wait_for_deployment,
    wait_for_modelapi_ready,
)

CREDENTIAL_SECRET_PREFIX = "kaos-aib"
CREDENTIAL_MOUNT_PATH = "/var/run/aib"

pytestmark = [
    pytest.mark.aib,
    pytest.mark.skipif(
        not os.environ.get("KAOS_AIB_E2E"),
        reason="agent-auth e2e requires an AIB+sync install; set KAOS_AIB_E2E=1",
    ),
]


@pytest.fixture(scope="module")
def aib_namespace():
    """Create an isolated namespace for the agent-auth e2e.

    Deliberately independent of the shared ``gateway_setup`` fixture: this test
    runs against a cluster that the ``kind-e2e-aib`` make target installed with
    auth, the identity broker, and the sync service already wired in.
    """
    namespace = f"e2e-aib-{int(time.time()) % 100000}"
    kubectl("create", "namespace", namespace)
    yield namespace
    try:
        kubectl("delete", "namespace", namespace, "--wait=false")
    except Exception:
        pass


def _get_json(resource: str, name: str, namespace: str) -> dict:
    out = kubectl("get", resource, name, "-n", namespace, "-o", "json")
    return json.loads(str(out))


def _wait_for_secret(namespace: str, name: str, timeout: int = 180) -> dict:
    """Poll until the sync service has provisioned the credential Secret."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            return _get_json("secret", name, namespace)
        except Exception as exc:  # secret not created yet
            last_err = exc
            time.sleep(2)
    raise TimeoutError(
        f"credential secret {namespace}/{name} not created after {timeout}s "
        f"(last error: {last_err})"
    )


def test_sync_provisions_and_operator_mounts_agent_credentials(aib_namespace: str):
    """Sync mints AIB credentials into a Secret the operator mounts into the pod."""
    namespace = aib_namespace
    modelapi_name = "aib-mock-proxy"
    agent_name = "aib-cred-agent"
    secret_name = f"{CREDENTIAL_SECRET_PREFIX}-{agent_name}"

    # A LiteLLM proxy ModelAPI gives the agent a backend so it can roll out.
    modelapi_spec = create_modelapi_resource(namespace, modelapi_name)
    create_custom_resource(modelapi_spec, namespace)
    wait_for_deployment(namespace, f"modelapi-{modelapi_name}", timeout=180)
    wait_for_modelapi_ready(namespace, modelapi_name, timeout=180)

    agent_spec = create_agent_resource(
        namespace=namespace,
        modelapi_name=modelapi_name,
        mcpserver_names=[],
        agent_name=agent_name,
    )
    create_custom_resource(agent_spec, namespace)

    # 1. The sync service must mint credentials and write the per-agent Secret.
    secret = _wait_for_secret(namespace, secret_name)
    assert secret["type"] == "Opaque"
    data = secret.get("data", {})
    assert data.get("client_id"), "secret missing non-empty client_id"
    assert data.get("client_secret"), "secret missing non-empty client_secret"

    # 2. The operator must mount the Secret into the agent Deployment.
    wait_for_deployment(namespace, f"agent-{agent_name}", timeout=180)
    deployment = _get_json("deployment", f"agent-{agent_name}", namespace)
    pod_spec = deployment["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]

    env_by_name = {e["name"]: e for e in container.get("env", [])}
    client_id_env = env_by_name.get("AGENT_AUTH_CLIENT_ID")
    assert client_id_env is not None, "AGENT_AUTH_CLIENT_ID env not injected"
    assert (
        client_id_env["valueFrom"]["secretKeyRef"]["name"] == secret_name
    ), "AGENT_AUTH_CLIENT_ID does not reference the credential secret"

    client_secret_env = env_by_name.get("AGENT_AUTH_CLIENT_SECRET")
    assert client_secret_env is not None, "AGENT_AUTH_CLIENT_SECRET env not injected"
    assert (
        client_secret_env["valueFrom"]["secretKeyRef"]["name"] == secret_name
    ), "AGENT_AUTH_CLIENT_SECRET does not reference the credential secret"

    # The credential secret is mounted read-only at the conventional path.
    secret_volumes = [
        v
        for v in pod_spec.get("volumes", [])
        if v.get("secret", {}).get("secretName") == secret_name
    ]
    assert secret_volumes, f"no volume backed by secret {secret_name}"
    volume_name = secret_volumes[0]["name"]
    mounts = [
        m
        for m in container.get("volumeMounts", [])
        if m["name"] == volume_name and m["mountPath"] == CREDENTIAL_MOUNT_PATH
    ]
    assert mounts, f"credential volume not mounted at {CREDENTIAL_MOUNT_PATH}"
    assert mounts[0].get("readOnly") is True, "credential mount must be read-only"

    # 3. The agent pod must come up with the credentials loaded.
    pods = json.loads(
        str(
            kubectl(
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                f"agent={agent_name}",
                "-o",
                "json",
            )
        )
    )
    assert pods["items"], "no agent pods scheduled"
    phases = {p["status"]["phase"] for p in pods["items"]}
    assert "Running" in phases, f"agent pod not Running (phases={phases})"
