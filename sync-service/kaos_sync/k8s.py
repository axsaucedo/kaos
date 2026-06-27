"""Kubernetes-backed Secret store and resource lister.

Wraps the Kubernetes client so the reconcile loop can read/write per-agent credential
Secrets and list KAOS custom resources. Imported only by the runtime entrypoint; the
reconcile logic depends on the :class:`kaos_sync.reconcile.SecretStore` protocol, not on
this module, so tests need no cluster.
"""

from __future__ import annotations

from typing import List

from kubernetes import client, config

KAOS_GROUP = "kaos.tools"
KAOS_VERSION = "v1alpha1"
AGENT_PLURAL = "agents"
MCPSERVER_PLURAL = "mcpservers"
MODELAPI_PLURAL = "modelapis"


def load_kube_config() -> None:
    """Load in-cluster config, falling back to local kubeconfig for development."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


class KubeSecretStore:
    """Reads and upserts Opaque Secrets via the core Kubernetes API."""

    def __init__(self, core_api: client.CoreV1Api | None = None) -> None:
        self._api = core_api or client.CoreV1Api()

    def get(self, namespace: str, name: str) -> dict[str, str] | None:
        try:
            secret = self._api.read_namespaced_secret(name, namespace)
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status == 404:
                return None
            raise
        data = secret.string_data or {}
        if secret.data:
            import base64

            for key, value in secret.data.items():
                data.setdefault(key, base64.b64decode(value).decode("utf-8"))
        return data

    def upsert(self, namespace: str, name: str, string_data: dict[str, str]) -> None:
        body = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=name,
                labels={"app.kubernetes.io/managed-by": "kaos-sync"},
            ),
            string_data=string_data,
            type="Opaque",
        )
        try:
            self._api.create_namespaced_secret(namespace, body)
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status != 409:
                raise
            self._api.replace_namespaced_secret(name, namespace, body)

    def list(self, namespaces: tuple[str, ...]) -> List[tuple[str, str]]:
        """List ``(namespace, name)`` of sync-managed credential Secrets.

        Only Secrets carrying the ``kaos-sync`` managed-by label are returned so pruning
        never removes Secrets owned by anything other than this service.
        """
        selector = "app.kubernetes.io/managed-by=kaos-sync"
        items: list[tuple[str, str]] = []
        if namespaces:
            for namespace in namespaces:
                result = self._api.list_namespaced_secret(namespace, label_selector=selector)
                items.extend((s.metadata.namespace, s.metadata.name) for s in result.items)
        else:
            result = self._api.list_secret_for_all_namespaces(label_selector=selector)
            items.extend((s.metadata.namespace, s.metadata.name) for s in result.items)
        return items

    def delete(self, namespace: str, name: str) -> bool:
        """Delete a Secret, treating a missing Secret (404) as already absent."""
        try:
            self._api.delete_namespaced_secret(name, namespace)
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status == 404:
                return False
            raise
        return True


class KaosResourceLister:
    """Lists KAOS Agent, MCPServer and ModelAPI resources across the configured namespaces."""

    def __init__(self, custom_api: client.CustomObjectsApi | None = None) -> None:
        self._api = custom_api or client.CustomObjectsApi()

    def _list(self, plural: str, kind: str, namespaces: tuple[str, ...]) -> list[dict]:
        items: list[dict] = []
        if namespaces:
            for namespace in namespaces:
                result = self._api.list_namespaced_custom_object(
                    KAOS_GROUP, KAOS_VERSION, namespace, plural
                )
                items.extend(result.get("items", []))
        else:
            result = self._api.list_cluster_custom_object(KAOS_GROUP, KAOS_VERSION, plural)
            items.extend(result.get("items", []))
        for item in items:
            item.setdefault("kind", kind)
        return items

    def list_resources(self, namespaces: tuple[str, ...]) -> list[dict]:
        return (
            self._list(MCPSERVER_PLURAL, "MCPServer", namespaces)
            + self._list(MODELAPI_PLURAL, "ModelAPI", namespaces)
            + self._list(AGENT_PLURAL, "Agent", namespaces)
        )
