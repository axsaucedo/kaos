"""Live authorization matrix for ServiceAccount identity and the in-chart PDP."""

import json
import os
from pathlib import Path
import subprocess
import time

import httpx
import pytest
from sh import kubectl

from e2e.conftest import (
    create_agent_resource,
    create_custom_resource,
    create_modelapi_resource,
    get_next_port,
    wait_for_deployment,
    wait_for_modelapi_ready,
)

POLICY_CONFIGMAP_NAME = os.environ.get(
    "KAOS_AUTHZ_POLICY_CONFIGMAP", "kaos-authz-policy"
)
POLICY_CONFIGMAP_NAMESPACE = os.environ.get(
    "KAOS_AUTHZ_POLICY_NAMESPACE", "kaos-system"
)
EVIDENCE_FILE = os.environ.get("KAOS_AUTHZ_EVIDENCE_FILE")

pytestmark = pytest.mark.skipif(
    not os.environ.get("KAOS_AUTHZ_E2E"),
    reason="authorization e2e requires KAOS_AUTHZ_E2E=1",
)


@pytest.fixture(scope="module")
def authz_namespace():
    namespace = f"e2e-authz-{int(time.time()) % 100000}"
    kubectl("create", "namespace", namespace)
    yield namespace
    kubectl("delete", "namespace", namespace, "--wait=false", _ok_code=[0, 1])


@pytest.fixture(scope="module")
def gateway_base_url():
    service = str(
        kubectl(
            "get",
            "service",
            "-n",
            "envoy-gateway-system",
            "-l",
            "gateway.envoyproxy.io/owning-gateway-name=kaos-gateway",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        )
    ).strip()
    assert service, "Envoy Gateway data-plane Service not found"
    port = get_next_port()
    process = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"service/{service}",
            f"{port}:80",
            "-n",
            "envoy-gateway-system",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Gateway port-forward exited before becoming ready")
        try:
            httpx.get(base_url, timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        process.terminate()
        raise TimeoutError("Gateway port-forward did not become ready")
    yield base_url
    process.terminate()
    process.wait(timeout=5)


def _wait_for_service_account(namespace: str, name: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = kubectl(
            "get",
            "serviceaccount",
            name,
            "-n",
            namespace,
            _ok_code=[0, 1],
        )
        if name in str(result):
            return
        time.sleep(1)
    raise TimeoutError(f"ServiceAccount {namespace}/{name} was not created")


def _wait_for_policy_data(
    namespace: str, agents: list[str], timeout: int = 180
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = kubectl(
                "get",
                "configmap",
                POLICY_CONFIGMAP_NAME,
                "-n",
                POLICY_CONFIGMAP_NAMESPACE,
                "-o",
                "jsonpath={.data.data\\.json}",
            )
            data = json.loads(str(raw))
            projected = data["kaos"]
            if all(
                f"kaos://agent/{namespace}/{name}" in projected["agents"]
                for name in agents
            ):
                assert projected["jwks"], "cluster JWKS was not projected"
                return data
        except (KeyError, json.JSONDecodeError, TypeError):
            pass
        time.sleep(2)
    raise TimeoutError("ServiceAccount issuer data was not projected")


def _request_until(url: str, token: str | None, expected, timeout: int = 120):
    headers = {"x-agent-authorization": f"Bearer {token}"} if token else {}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = httpx.get(url, headers=headers, timeout=10)
            if expected(last.status_code):
                return last
        except httpx.HTTPError:
            pass
        time.sleep(2)
    status = last.status_code if last is not None else None
    body = last.text[:500] if last is not None else ""
    raise AssertionError(
        f"request to {url} never reached expected status; last={status} {body}"
    )


def _record_evidence(outcomes: dict) -> None:
    if not EVIDENCE_FILE:
        return
    path = Path(EVIDENCE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8")


def test_live_serviceaccount_authorization_matrix(
    authz_namespace: str, gateway_base_url: str
):
    namespace = authz_namespace
    granted_target = "authz-target"
    other_target = "authz-other"
    granted_agent = "authz-granted"
    ungranted_agent = "authz-ungranted"

    for modelapi in (granted_target, other_target):
        create_custom_resource(create_modelapi_resource(namespace, modelapi), namespace)
        wait_for_deployment(namespace, f"modelapi-{modelapi}", timeout=240)
        wait_for_modelapi_ready(namespace, modelapi, timeout=240)

    create_custom_resource(
        create_agent_resource(namespace, granted_target, [], granted_agent), namespace
    )
    create_custom_resource(
        create_agent_resource(namespace, other_target, [], ungranted_agent), namespace
    )

    granted_sa = f"kaos-agent-{granted_agent}"
    ungranted_sa = f"kaos-agent-{ungranted_agent}"
    _wait_for_service_account(namespace, granted_sa)
    _wait_for_service_account(namespace, ungranted_sa)
    _wait_for_policy_data(namespace, [granted_agent, ungranted_agent])

    granted_token = str(
        kubectl(
            "create",
            "token",
            granted_sa,
            "-n",
            namespace,
            "--audience=kaos-gateway",
            "--duration=10m",
        )
    ).strip()
    ungranted_token = str(
        kubectl(
            "create",
            "token",
            ungranted_sa,
            "-n",
            namespace,
            "--audience=kaos-gateway",
            "--duration=10m",
        )
    ).strip()
    target_url = (
        f"{gateway_base_url}/{namespace}/modelapi/{granted_target}/health/liveliness"
    )

    outcomes = {}
    allowed = _request_until(target_url, granted_token, lambda status: status == 200)
    outcomes["granted_valid_token"] = {"status": allowed.status_code}

    denied = _request_until(target_url, ungranted_token, lambda status: status == 403)
    outcomes["ungranted_valid_token"] = {"status": denied.status_code}

    no_token = _request_until(target_url, None, lambda status: 400 <= status < 500)
    outcomes["no_token"] = {"status": no_token.status_code}

    replicas = str(
        kubectl(
            "get",
            "deployment",
            "kaos-pdp",
            "-n",
            "kaos-system",
            "-o",
            "jsonpath={.spec.replicas}",
        )
    ).strip()
    try:
        kubectl("scale", "deployment/kaos-pdp", "-n", "kaos-system", "--replicas=0")
        kubectl(
            "wait",
            "--for=delete",
            "pod",
            "-n",
            "kaos-system",
            "-l",
            "app.kubernetes.io/name=kaos-pdp",
            "--timeout=120s",
        )
        pdp_down = _request_until(
            target_url, granted_token, lambda status: status >= 400
        )
        outcomes["pdp_down"] = {"status": pdp_down.status_code}
    finally:
        kubectl(
            "scale",
            "deployment/kaos-pdp",
            "-n",
            "kaos-system",
            f"--replicas={replicas or '2'}",
        )
        kubectl(
            "rollout",
            "status",
            "deployment/kaos-pdp",
            "-n",
            "kaos-system",
            "--timeout=180s",
        )

    recovered = _request_until(target_url, granted_token, lambda status: status == 200)
    outcomes["pdp_recovered"] = {"status": recovered.status_code}
    _record_evidence(outcomes)
