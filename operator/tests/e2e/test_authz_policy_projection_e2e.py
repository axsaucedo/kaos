"""End-to-end test for the KAOS-owned authorization policy projection.

Validates the Model-1 authorization path where the operator projects KAOS
resources into a single policy ConfigMap that the enforcement engine (OPA in
external authorization engine) mounts:

1. The operator's authorization projection controller renders a static
   ``policy.rego`` and, in the default ``automated`` policy-data source, a
   ``data.json`` grant graph keyed on each agent's logical identity.
2. Repeated reconciles are idempotent: the rego is stable and the grant data
   keeps every projected agent, proving the projection never clobbers prior
   grants as new agents appear.

This test is opt-in: it requires a cluster installed with the KAOS
authorization provider and the policy ConfigMap projection target
(``--authz-provider kaos --policy-data-source automated
--policy-configmap-name ... --policy-configmap-namespace ...``); see the
``kind-e2e-authz`` make target. It is skipped unless ``KAOS_AUTHZ_E2E`` is set
so the default E2E suite, which runs without authorization, is unaffected.
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

POLICY_CONFIGMAP_NAME = os.environ.get(
    "KAOS_AUTHZ_POLICY_CONFIGMAP", "kaos-authz-policy"
)
POLICY_CONFIGMAP_NAMESPACE = os.environ.get(
    "KAOS_AUTHZ_POLICY_NAMESPACE", "kaos-system"
)

pytestmark = [
    pytest.mark.aib,
    pytest.mark.skipif(
        not os.environ.get("KAOS_AUTHZ_E2E"),
        reason="authorization projection e2e requires a KAOS-authz install; "
        "set KAOS_AUTHZ_E2E=1",
    ),
]


@pytest.fixture(scope="module")
def authz_namespace():
    """Create an isolated namespace for the authorization projection e2e."""
    namespace = f"e2e-authz-{int(time.time()) % 100000}"
    kubectl("create", "namespace", namespace)
    yield namespace
    try:
        kubectl("delete", "namespace", namespace, "--wait=false")
    except Exception:
        pass


def _get_policy_configmap() -> dict:
    out = kubectl(
        "get",
        "configmap",
        POLICY_CONFIGMAP_NAME,
        "-n",
        POLICY_CONFIGMAP_NAMESPACE,
        "-o",
        "json",
    )
    return json.loads(str(out))


def _wait_for_policy_key(key: str, timeout: int = 180) -> dict:
    """Poll until the policy ConfigMap exists and carries the named key."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            cm = _get_policy_configmap()
            if key in cm.get("data", {}):
                return cm
        except Exception as exc:  # ConfigMap not created yet
            last_err = exc
        time.sleep(3)
    raise TimeoutError(
        f"policy ConfigMap key {key!r} not projected after {timeout}s "
        f"(last error: {last_err})"
    )


def _grant_subjects(cm: dict) -> dict:
    """Return the data.kaos.grants map from the projected data.json key."""
    data_json = cm.get("data", {}).get("data.json", "")
    assert data_json, "policy ConfigMap missing data.json"
    parsed = json.loads(data_json)
    return parsed.get("kaos", {}).get("grants", {})


def test_operator_projects_and_maintains_policy_configmap(authz_namespace: str):
    """The operator renders the policy ConfigMap and keeps grants across agents."""
    namespace = authz_namespace
    modelapi_name = "authz-mock-proxy"
    first_agent = "authz-agent-a"
    second_agent = "authz-agent-b"

    # A LiteLLM proxy ModelAPI gives the agents a backend so they can roll out.
    modelapi_spec = create_modelapi_resource(namespace, modelapi_name)
    create_custom_resource(modelapi_spec, namespace)
    wait_for_deployment(namespace, f"modelapi-{modelapi_name}", timeout=180)
    wait_for_modelapi_ready(namespace, modelapi_name, timeout=180)

    create_custom_resource(
        create_agent_resource(
            namespace=namespace,
            modelapi_name=modelapi_name,
            mcpserver_names=[],
            agent_name=first_agent,
        ),
        namespace,
    )

    # 1. The operator must render the static rego and the grant data.
    cm = _wait_for_policy_key("policy.rego")
    assert cm["data"]["policy.rego"].strip(), "policy.rego is empty"
    cm = _wait_for_policy_key("data.json")
    rego_before = cm["data"]["policy.rego"]

    def _has_agent(agent_name: str, timeout: int = 180) -> dict:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            current = _get_policy_configmap()
            grants = _grant_subjects(current)
            key = f"kaos://agent/{namespace}/{agent_name}"
            if any(agent_name in k for k in grants) or key in grants:
                return current
            last = list(grants.keys())
            time.sleep(3)
        raise TimeoutError(
            f"agent {agent_name} not present in projected grants after {timeout}s "
            f"(last grant keys: {last})"
        )

    _has_agent(first_agent)

    # 2. Adding a second agent must extend the grant data without dropping the
    #    first agent and without rewriting the static policy.
    create_custom_resource(
        create_agent_resource(
            namespace=namespace,
            modelapi_name=modelapi_name,
            mcpserver_names=[],
            agent_name=second_agent,
        ),
        namespace,
    )
    _has_agent(second_agent)

    final = _get_policy_configmap()
    grants = _grant_subjects(final)
    present = {k for k in grants}
    assert any(
        first_agent in k for k in present
    ), f"first agent grant dropped after second reconcile (keys={present})"
    assert any(
        second_agent in k for k in present
    ), f"second agent grant missing (keys={present})"
    assert (
        final["data"]["policy.rego"] == rego_before
    ), "static policy.rego changed across reconciles"
