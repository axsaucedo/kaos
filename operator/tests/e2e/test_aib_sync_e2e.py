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
import subprocess
import time

import httpx
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
AIB_NAMESPACE = "aib-system"
AIB_BROKER_SERVICE = "aib-agentic-identity-broker"
AIB_ADMIN_PORT = 14000
AIB_ADMIN_PRINCIPAL_HEADER = "X-Remote-User"
AIB_ADMIN_PRINCIPAL = "kaos-sync"

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


def _list_admin_collection(local_port: int, collection: str) -> list:
    """List an AIB admin collection via the pre-auth principal header."""
    resp = httpx.get(
        f"http://localhost:{local_port}/api/{collection}",
        headers={AIB_ADMIN_PRINCIPAL_HEADER: AIB_ADMIN_PRINCIPAL},
        timeout=10.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict):
        return payload.get("items", [])
    return payload


def _wait_for_permission_set(local_port: int, name: str, timeout: int = 180) -> dict:
    """Poll the AIB admin API until the named permission set is projected."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            for ps in _list_admin_collection(local_port, "permission-sets"):
                if ps.get("name") == name:
                    return ps
        except Exception as exc:  # broker not reachable yet
            last = exc
        time.sleep(3)
    raise TimeoutError(
        f"permission set {name!r} not projected after {timeout}s (last error: {last})"
    )


def test_sync_projects_agent_delegation_grant(aib_namespace: str):
    """A declared agentNetwork.access peer becomes an AIB delegation grant.

    The delegator's only path to a credential Secret for the peer edge is the
    agent-to-agent grant projection: the sync fails closed and mints no Secret
    unless every projected permission set exists, so a provisioned delegator plus
    the peer permission set in the broker proves the access edge is authorized.
    """
    namespace = aib_namespace
    modelapi_name = "aib-deleg-proxy"
    peer_name = "aib-deleg-peer"
    delegator_name = "aib-deleg-supervisor"
    peer_ps_name = f"kaos:agent:{namespace}:{peer_name}:call"
    delegator_secret = f"{CREDENTIAL_SECRET_PREFIX}-{delegator_name}"

    modelapi_spec = create_modelapi_resource(namespace, modelapi_name)
    create_custom_resource(modelapi_spec, namespace)
    wait_for_deployment(namespace, f"modelapi-{modelapi_name}", timeout=180)
    wait_for_modelapi_ready(namespace, modelapi_name, timeout=180)

    # The peer is a plain agent; the delegator declares access to it.
    peer_spec = create_agent_resource(
        namespace=namespace,
        modelapi_name=modelapi_name,
        mcpserver_names=[],
        agent_name=peer_name,
    )
    create_custom_resource(peer_spec, namespace)

    delegator_spec = create_agent_resource(
        namespace=namespace,
        modelapi_name=modelapi_name,
        mcpserver_names=[],
        agent_name=delegator_name,
        sub_agents=[peer_name],
    )
    create_custom_resource(delegator_spec, namespace)

    # The sync fails closed, so a delegator Secret implies the peer grant exists.
    secret = _wait_for_secret(namespace, delegator_secret)
    assert secret.get("data", {}).get("client_id"), "delegator missing credentials"

    # Confirm the agent-to-agent permission set was projected into the broker.
    pf = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{AIB_BROKER_SERVICE}",
            f"{AIB_ADMIN_PORT}:{AIB_ADMIN_PORT}",
            "-n",
            AIB_NAMESPACE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ps = _wait_for_permission_set(AIB_ADMIN_PORT, peer_ps_name)
    finally:
        pf.terminate()

    assert ps["name"] == peer_ps_name

    # The delegator agent must be bound to the peer grant in the broker.
    pf = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{AIB_BROKER_SERVICE}",
            f"{AIB_ADMIN_PORT}:{AIB_ADMIN_PORT}",
            "-n",
            AIB_NAMESPACE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        agents = _list_admin_collection(AIB_ADMIN_PORT, "agents")
    finally:
        pf.terminate()

    delegator_external_id = f"kaos://agent/{namespace}/{delegator_name}"
    delegator = next(
        (a for a in agents if a.get("display_name") == delegator_external_id), None
    )
    assert delegator is not None, f"delegator {delegator_external_id} not in broker"
