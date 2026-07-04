"""End-to-end tests for the MemoryStore resource and agent memory binding.

Validates the memory control plane against a live KIND cluster:
- A local-mode MemoryStore deploys the memory service and reports Ready.
- An Agent bound to the store receives the remote memory wiring (endpoint,
  scope, identity) and reports the store as a linked, non-degraded resource.
- An Agent bound to a missing store keeps serving with a MemoryDegraded
  condition rather than failing.

The memory service binds its models lazily, so a local-mode store reaches
Ready from store reachability alone (no real embedding backend required); a
mock proxy ModelAPI satisfies the model references.
"""

import time
import pytest
from sh import kubectl

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    create_modelapi_resource,
    wait_for_modelapi_ready,
)


def _jsonpath(resource: str, name: str, namespace: str, path: str) -> str:
    return str(
        kubectl(
            "get",
            resource,
            name,
            "-n",
            namespace,
            "-o",
            f"jsonpath={{{path}}}",
            _ok_code=[0, 1],
        )
    ).strip()


def wait_for_memorystore_ready(namespace: str, name: str, timeout: int = 240):
    """Wait for a MemoryStore CR to report Ready."""
    start = time.time()
    last_phase = ""
    while time.time() - start < timeout:
        ready = _jsonpath("memorystore", name, namespace, ".status.ready")
        last_phase = _jsonpath("memorystore", name, namespace, ".status.phase")
        if ready == "true" and last_phase == "Ready":
            return
        time.sleep(3)
    message = _jsonpath("memorystore", name, namespace, ".status.message")
    raise TimeoutError(
        f"MemoryStore {name} not ready after {timeout}s "
        f"(phase={last_phase}, message={message})"
    )


def _pod_env(namespace: str, deployment: str) -> dict:
    """Read the container env of a deployment's pod template as a name→value map."""
    names = str(
        kubectl(
            "get",
            "deployment",
            deployment,
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.template.spec.containers[0].env[*].name}",
            _ok_code=[0, 1],
        )
    ).split()
    values = str(
        kubectl(
            "get",
            "deployment",
            deployment,
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.template.spec.containers[0].env[*].value}",
            _ok_code=[0, 1],
        )
    ).split()
    # env entries with valueFrom have no literal value; align by name where present.
    return dict(zip(names, values))


def _create_memorystore(namespace: str, name: str, modelapi_name: str):
    create_custom_resource(
        {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "MemoryStore",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "engine": "mem0",
                "storage": {
                    "type": "local",
                    "local": {
                        "provider": "chroma",
                        "persistentVolume": {"size": "1Gi"},
                    },
                },
                "models": {
                    "summarization": {
                        "modelAPI": modelapi_name,
                        "model": "gpt-4o-mini",
                    },
                    "embedding": {
                        "modelAPI": modelapi_name,
                        "model": "text-embedding-3-small",
                    },
                },
            },
        },
        namespace,
    )


@pytest.mark.asyncio
async def test_memorystore_local_deploys_and_becomes_ready(test_namespace: str):
    """A local-mode MemoryStore deploys the service and reports Ready with an endpoint."""
    modelapi_name = "mem-model"
    create_custom_resource(
        create_modelapi_resource(test_namespace, modelapi_name), test_namespace
    )
    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=120)
    wait_for_modelapi_ready(test_namespace, modelapi_name, timeout=120)

    store_name = "local-store"
    _create_memorystore(test_namespace, store_name, modelapi_name)

    wait_for_deployment(test_namespace, f"memorystore-{store_name}", timeout=180)
    wait_for_memorystore_ready(test_namespace, store_name, timeout=240)

    endpoint = _jsonpath("memorystore", store_name, test_namespace, ".status.endpoint")
    assert endpoint == (
        f"http://memorystore-{store_name}.{test_namespace}.svc.cluster.local:8080"
    )

    # The service env carries the KAOS_MEMORY_* storage and model contract.
    env = _pod_env(test_namespace, f"memorystore-{store_name}")
    assert env.get("KAOS_MEMORY_STORAGE_TYPE") == "local"
    assert env.get("KAOS_MEMORY_LOCAL_PATH") == "/data/memory"


@pytest.mark.asyncio
async def test_agent_binds_ready_memorystore(test_namespace: str):
    """An agent bound to a ready store gets remote memory wiring and a linked, non-degraded status."""
    modelapi_name = "mem-model-bind"
    create_custom_resource(
        create_modelapi_resource(test_namespace, modelapi_name), test_namespace
    )
    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=120)
    wait_for_modelapi_ready(test_namespace, modelapi_name, timeout=120)

    store_name = "bind-store"
    _create_memorystore(test_namespace, store_name, modelapi_name)
    wait_for_deployment(test_namespace, f"memorystore-{store_name}", timeout=180)
    wait_for_memorystore_ready(test_namespace, store_name, timeout=240)

    agent_name = "mem-agent"
    create_custom_resource(
        {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": agent_name, "namespace": test_namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "gpt-4o-mini",
                "config": {
                    "description": "memory agent",
                    "instructions": "You are a memory-enabled agent.",
                    "memory": {
                        "type": "remote",
                        "memoryStore": store_name,
                        "scope": "user",
                        "tools": "all",
                    },
                },
            },
        },
        test_namespace,
    )

    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    env = _pod_env(test_namespace, f"agent-{agent_name}")
    assert env.get("MEMORY_TYPE") == "remote"
    assert env.get("MEMORY_STORE_ENDPOINT") == (
        f"http://memorystore-{store_name}.{test_namespace}.svc.cluster.local:8080"
    )
    assert env.get("MEMORY_SCOPE") == "user"
    assert env.get("AGENT_IDENTITY") == f"kaos://agent/{test_namespace}/{agent_name}"

    # Status links the store and reports memory as not degraded.
    linked = _jsonpath(
        "agent", agent_name, test_namespace, ".status.linkedResources.memorystore"
    )
    assert linked == store_name

    degraded = _jsonpath(
        "agent",
        agent_name,
        test_namespace,
        ".status.conditions[?(@.type=='MemoryDegraded')].status",
    )
    assert degraded == "False"


@pytest.mark.asyncio
async def test_agent_degraded_when_store_missing(test_namespace: str):
    """An agent bound to a missing store keeps serving with a MemoryDegraded condition."""
    modelapi_name = "mem-model-degraded"
    create_custom_resource(
        create_modelapi_resource(test_namespace, modelapi_name), test_namespace
    )
    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=120)
    wait_for_modelapi_ready(test_namespace, modelapi_name, timeout=120)

    agent_name = "degraded-agent"
    create_custom_resource(
        {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": agent_name, "namespace": test_namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "gpt-4o-mini",
                "config": {
                    "description": "degraded memory agent",
                    "instructions": "You are an agent with a missing memory store.",
                    "memory": {"type": "remote", "memoryStore": "does-not-exist"},
                },
            },
        },
        test_namespace,
    )

    # The agent Deployment is still created (memory never gates serving).
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    env = _pod_env(test_namespace, f"agent-{agent_name}")
    assert env.get("MEMORY_TYPE") == "remote"
    assert "MEMORY_STORE_ENDPOINT" not in env

    deadline = time.time() + 60
    degraded = ""
    while time.time() < deadline:
        degraded = _jsonpath(
            "agent",
            agent_name,
            test_namespace,
            ".status.conditions[?(@.type=='MemoryDegraded')].status",
        )
        if degraded == "True":
            break
        time.sleep(3)
    assert degraded == "True"
