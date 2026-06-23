"""Kubernetes-backed Secret store and resource lister.

Wraps the Kubernetes client so the reconcile loop can read/write per-agent credential
Secrets and list KAOS custom resources. Imported only by the runtime entrypoint; the
reconcile logic depends on the :class:`kaos_sync.reconcile.SecretStore` protocol, not on
this module, so tests need no cluster.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator, List

from kubernetes import client, config, watch

logger = logging.getLogger("kaos_sync")

KAOS_GROUP = "kaos.tools"
KAOS_VERSION = "v1alpha1"
AGENT_PLURAL = "agents"
MCPSERVER_PLURAL = "mcpservers"
MODELAPI_PLURAL = "modelapis"

_WATCHED_PLURALS = (
    (MCPSERVER_PLURAL, "MCPServer"),
    (MODELAPI_PLURAL, "ModelAPI"),
    (AGENT_PLURAL, "Agent"),
)


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

    def upsert(
        self,
        namespace: str,
        name: str,
        string_data: dict[str, str],
        annotations: dict[str, str] | None = None,
    ) -> None:
        body = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=name,
                labels={"app.kubernetes.io/managed-by": "kaos-sync"},
                annotations=annotations or None,
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

    def get_annotation(self, namespace: str, name: str, key: str) -> str | None:
        """Read a single annotation off a Secret, returning ``None`` if absent or missing."""
        try:
            secret = self._api.read_namespaced_secret(name, namespace)
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status == 404:
                return None
            raise
        annotations = (secret.metadata.annotations if secret.metadata else None) or {}
        return annotations.get(key)

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


@dataclass(frozen=True)
class WatchEvent:
    """A single KAOS resource change observed by the watch layer."""

    type: str
    kind: str
    namespace: str
    name: str
    resource_version: str


def _stream_plural(
    api: "client.CustomObjectsApi",
    plural: str,
    kind: str,
    namespaces: tuple[str, ...],
    *,
    timeout_seconds: int,
) -> Iterator[WatchEvent]:
    """Yield change events for a single CRD plural until the watch stream ends.

    Watches each configured namespace (or cluster-wide when none are set). A 410 Gone /
    expired resourceVersion surfaces as the stream simply ending, so the caller restarts
    it with a fresh list — the watch never carries a stale resourceVersion forward.
    """
    w = watch.Watch()
    targets = namespaces or ("",)
    for namespace in targets:
        if namespace:
            stream = w.stream(
                api.list_namespaced_custom_object,
                KAOS_GROUP,
                KAOS_VERSION,
                namespace,
                plural,
                timeout_seconds=timeout_seconds,
            )
        else:
            stream = w.stream(
                api.list_cluster_custom_object,
                KAOS_GROUP,
                KAOS_VERSION,
                plural,
                timeout_seconds=timeout_seconds,
            )
        for event in stream:
            obj = event.get("object", {}) or {}
            meta = obj.get("metadata", {}) if isinstance(obj, dict) else {}
            yield WatchEvent(
                type=str(event.get("type", "")),
                kind=kind,
                namespace=str(meta.get("namespace", "") or ""),
                name=str(meta.get("name", "") or ""),
                resource_version=str(meta.get("resourceVersion", "") or ""),
            )


class KubeWatchSource:
    """Background watch over the three KAOS CRDs that signals a callback on any change.

    One daemon thread per plural streams change events and invokes ``on_event`` for each.
    A stream that ends or errors (disconnect, 410 expired resourceVersion, transient API
    failure) is simply re-established after a short delay — the watch is a *liveness hint*
    that feeds a debounced full-resync worker, so it never needs to carry resourceVersion
    state across reconnects and never crashes the process.
    """

    def __init__(
        self,
        namespaces: tuple[str, ...],
        on_event: Callable[[WatchEvent], None],
        *,
        custom_api: "client.CustomObjectsApi | None" = None,
        timeout_seconds: int = 300,
        reconnect_delay_seconds: float = 1.0,
    ) -> None:
        self._namespaces = namespaces
        self._on_event = on_event
        self._api = custom_api or client.CustomObjectsApi()
        self._timeout_seconds = timeout_seconds
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for plural, kind in _WATCHED_PLURALS:
            thread = threading.Thread(
                target=self._run_plural,
                args=(plural, kind),
                name=f"watch-{plural}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def _run_plural(self, plural: str, kind: str) -> None:
        while not self._stop.is_set():
            try:
                for event in _stream_plural(
                    self._api,
                    plural,
                    kind,
                    self._namespaces,
                    timeout_seconds=self._timeout_seconds,
                ):
                    if self._stop.is_set():
                        return
                    self._on_event(event)
            except Exception:  # noqa: BLE001 - a watch error must never kill the process
                logger.debug("watch stream for %s ended; re-establishing", plural, exc_info=True)
            if self._stop.wait(self._reconnect_delay_seconds):
                return


class KubeLeaseBackend:
    """A ``coordination.k8s.io/v1`` Lease used to elect a single active reconciler.

    ``try_acquire_or_renew`` returns True when this identity holds (or just took) the
    Lease and False when another identity holds an unexpired Lease. Acquisition is
    optimistic: a lost update (HTTP 409) or a creation race is reported as not-acquired
    rather than raising, so a losing replica simply stands by and retries.
    """

    def __init__(
        self,
        *,
        name: str,
        namespace: str,
        identity: str,
        lease_duration_seconds: float,
        coordination_api: "client.CoordinationV1Api | None" = None,
    ) -> None:
        self._name = name
        self._namespace = namespace
        self._identity = identity
        self._lease_duration = int(lease_duration_seconds)
        self._api = coordination_api or client.CoordinationV1Api()

    def try_acquire_or_renew(self) -> bool:
        now = datetime.now(timezone.utc)
        try:
            lease = self._api.read_namespaced_lease(self._name, self._namespace)
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status == 404:
                return self._create(now)
            raise
        spec = lease.spec
        holder = spec.holder_identity
        if holder == self._identity:
            spec.renew_time = now
            return self._update(lease)
        if holder is None or self._is_expired(spec, now):
            spec.holder_identity = self._identity
            spec.acquire_time = now
            spec.renew_time = now
            spec.lease_duration_seconds = self._lease_duration
            return self._update(lease)
        return False

    def _is_expired(self, spec, now: datetime) -> bool:
        renew = spec.renew_time
        if renew is None:
            return True
        ttl = spec.lease_duration_seconds or self._lease_duration
        return (now - renew).total_seconds() > ttl

    def _create(self, now: datetime) -> bool:
        body = client.V1Lease(
            metadata=client.V1ObjectMeta(name=self._name, namespace=self._namespace),
            spec=client.V1LeaseSpec(
                holder_identity=self._identity,
                acquire_time=now,
                renew_time=now,
                lease_duration_seconds=self._lease_duration,
            ),
        )
        try:
            self._api.create_namespaced_lease(self._namespace, body)
            return True
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status == 409:
                return False
            raise

    def _update(self, lease) -> bool:
        try:
            self._api.replace_namespaced_lease(self._name, self._namespace, lease)
            return True
        except client.ApiException as exc:  # type: ignore[attr-defined]
            if exc.status == 409:
                return False
            raise
