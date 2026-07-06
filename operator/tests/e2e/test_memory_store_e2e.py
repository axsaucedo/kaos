"""End-to-end behavioural tests for the MemoryStore data plane.

These assert the memory service's *behaviour* against a live KIND cluster, not
just that resources reconcile. They exercise the running service's HTTP
contract directly (write + recall) so the backend integration is verified end
to end:

- A local-mode (Chroma) MemoryStore deploys, reports Ready, and round-trips the
  short-term window verbatim through write/recall.
- Short-term memory is isolated per scope: one principal never sees another's
  turns even on the same store.
- Agent memory binding recovers: an agent bound to a missing store serves in a
  MemoryDegraded state and clears the condition once the store becomes Ready.

The assertions are deliberately model-independent. The short-term tier is
verbatim durable storage (no embedder/LLM), so a mock ModelAPI satisfies the
model references while the behaviour under test needs no real inference. Real
semantic long-term recall requires a real embedder and is covered by the
library tests and the pgvector example rather than here.
"""

import time

import httpx
import pytest
from sh import kubectl

from e2e.conftest import (
    create_custom_resource,
    create_modelapi_resource,
    get_next_port,
    port_forward,
    wait_for_deployment,
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


def _forward_memory_service(namespace: str, store_name: str):
    """Port-forward the memory service and wait for /healthz. Returns (process, base_url)."""
    local_port = get_next_port()
    process = port_forward(
        namespace, f"memorystore-{store_name}", local_port, remote_port=8080
    )
    base_url = f"http://localhost:{local_port}"
    deadline = time.time() + 30
    time.sleep(0.5)
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/healthz", timeout=2.0).status_code == 200:
                return process, base_url
        except Exception:
            pass
        time.sleep(0.5)
    process.terminate()
    raise TimeoutError(f"memory service for {store_name} not reachable after 30s")


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


def _deploy_ready_store(namespace: str, modelapi_name: str, store_name: str):
    """Create a mock ModelAPI and a local MemoryStore, and wait for both to be Ready."""
    create_custom_resource(
        create_modelapi_resource(namespace, modelapi_name), namespace
    )
    wait_for_deployment(namespace, f"modelapi-{modelapi_name}", timeout=120)
    wait_for_modelapi_ready(namespace, modelapi_name, timeout=120)

    _create_memorystore(namespace, store_name, modelapi_name)
    wait_for_deployment(namespace, f"memorystore-{store_name}", timeout=180)
    wait_for_memorystore_ready(namespace, store_name, timeout=240)


@pytest.mark.asyncio
async def test_short_term_round_trips_verbatim_through_the_service(test_namespace: str):
    """Turns written to a Ready store are recalled back verbatim in the short-term window."""
    _deploy_ready_store(test_namespace, "mem-model-rt", "rt-store")

    process, base_url = _forward_memory_service(test_namespace, "rt-store")
    try:
        scope = {"level": "session", "session_id": "run-roundtrip"}
        turns = [
            {"role": "user", "content": "my favourite port is 8080"},
            {"role": "assistant", "content": "noted, port 8080"},
        ]
        write = httpx.post(
            f"{base_url}/v1/write",
            json={"scope": scope, "turns": turns, "infer": False},
            timeout=30.0,
        )
        assert write.status_code == 200, write.text
        assert write.json()["accepted"] is True

        recall = httpx.post(
            f"{base_url}/v1/recall",
            json={"scope": scope, "query": "what port", "include_short_term": True},
            timeout=30.0,
        )
        assert recall.status_code == 200, recall.text
        recent = recall.json()["short_term"]["recent"]
        flattened = [tuple(pair) for pair in recent]
        assert ("user", "my favourite port is 8080") in flattened
        assert ("assistant", "noted, port 8080") in flattened
    finally:
        process.terminate()


@pytest.mark.asyncio
async def test_short_term_is_isolated_between_scopes(test_namespace: str):
    """Two principals writing to the same store never see each other's short-term turns."""
    _deploy_ready_store(test_namespace, "mem-model-iso", "iso-store")

    process, base_url = _forward_memory_service(test_namespace, "iso-store")
    try:
        alice = {"level": "user", "principal": "alice"}
        bob = {"level": "user", "principal": "bob"}
        httpx.post(
            f"{base_url}/v1/write",
            json={
                "scope": alice,
                "turns": [{"role": "user", "content": "alice secret token"}],
                "infer": False,
            },
            timeout=30.0,
        ).raise_for_status()
        httpx.post(
            f"{base_url}/v1/write",
            json={
                "scope": bob,
                "turns": [{"role": "user", "content": "bob private note"}],
                "infer": False,
            },
            timeout=30.0,
        ).raise_for_status()

        a_recent = httpx.post(
            f"{base_url}/v1/recall",
            json={"scope": alice, "query": "x", "include_short_term": True},
            timeout=30.0,
        ).json()["short_term"]["recent"]
        b_recent = httpx.post(
            f"{base_url}/v1/recall",
            json={"scope": bob, "query": "x", "include_short_term": True},
            timeout=30.0,
        ).json()["short_term"]["recent"]

        a_text = " ".join(content for _, content in (tuple(p) for p in a_recent))
        b_text = " ".join(content for _, content in (tuple(p) for p in b_recent))
        assert "alice secret token" in a_text
        assert "bob private note" not in a_text
        assert "bob private note" in b_text
        assert "alice secret token" not in b_text
    finally:
        process.terminate()


@pytest.mark.asyncio
async def test_agent_memory_binding_recovers_when_store_appears(test_namespace: str):
    """An agent bound to a missing store is MemoryDegraded, then recovers once the store is Ready."""
    modelapi_name = "mem-model-recover"
    create_custom_resource(
        create_modelapi_resource(test_namespace, modelapi_name), test_namespace
    )
    wait_for_deployment(test_namespace, f"modelapi-{modelapi_name}", timeout=120)
    wait_for_modelapi_ready(test_namespace, modelapi_name, timeout=120)

    store_name = "recover-store"
    agent_name = "recover-agent"
    create_custom_resource(
        {
            "apiVersion": "kaos.tools/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": agent_name, "namespace": test_namespace},
            "spec": {
                "modelAPI": modelapi_name,
                "model": "gpt-4o-mini",
                "config": {
                    "description": "recovering memory agent",
                    "instructions": "You are a memory-enabled agent.",
                    "memory": {"type": "remote", "memoryStore": store_name},
                },
            },
        },
        test_namespace,
    )

    # Memory never gates serving: the agent deploys even though the store is absent.
    wait_for_deployment(test_namespace, f"agent-{agent_name}", timeout=120)

    def _degraded() -> str:
        return _jsonpath(
            "agent",
            agent_name,
            test_namespace,
            ".status.conditions[?(@.type=='MemoryDegraded')].status",
        )

    deadline = time.time() + 60
    while time.time() < deadline and _degraded() != "True":
        time.sleep(3)
    assert _degraded() == "True"

    # Create the store; once Ready the agent's memory condition clears.
    _create_memorystore(test_namespace, store_name, modelapi_name)
    wait_for_deployment(test_namespace, f"memorystore-{store_name}", timeout=180)
    wait_for_memorystore_ready(test_namespace, store_name, timeout=240)

    deadline = time.time() + 120
    while time.time() < deadline and _degraded() != "False":
        time.sleep(3)
    assert _degraded() == "False"

    # The recovered agent now carries the remote memory wiring.
    linked = _jsonpath(
        "agent", agent_name, test_namespace, ".status.linkedResources.memorystore"
    )
    assert linked == store_name
