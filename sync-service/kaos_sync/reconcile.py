"""Reconciliation of desired AIB state and per-agent credential Secrets.

This module is I/O-free in itself: it orchestrates an :class:`AIBAdminClient` and a
:class:`SecretStore` (both protocols) so it can be unit tested with fakes. Concrete
implementations live in :mod:`kaos_sync.aib_client` and :mod:`kaos_sync.secrets`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol

from kaos_sync.projection import (
    DesiredAgent,
    DesiredState,
    is_kaos_agent_display_name,
    is_kaos_permission_set_name,
    is_kaos_service_client_id,
)


def credential_secret_name(prefix: str, agent_name: str) -> str:
    """Per-agent credential Secret name, derivable by both the sync service and operator."""
    return f"{prefix}-{agent_name}"


class AIBAdminClient(Protocol):
    def list(self, collection: str) -> List[dict]: ...

    def get(self, collection: str, resource_id: str) -> dict | None: ...

    def create_or_get(
        self, collection: str, match_field: str, match_value: str, body: dict
    ) -> str: ...

    def delete(self, collection: str, resource_id: str) -> bool: ...

    def mint_credentials(self, agent_id: str) -> dict: ...

    def revoke_credentials(self, agent_id: str) -> bool: ...


class SecretStore(Protocol):
    def get(self, namespace: str, name: str) -> dict[str, str] | None: ...

    def upsert(self, namespace: str, name: str, string_data: dict[str, str]) -> None: ...

    def list(self, namespaces: tuple[str, ...]) -> List[tuple[str, str]]: ...

    def delete(self, namespace: str, name: str) -> bool: ...


@dataclass
class AgentSync:
    """Outcome of reconciling a single agent."""

    external_id: str
    agent_id: str
    secret_namespace: str
    secret_name: str
    credentials_minted: bool


@dataclass
class PruneSummary:
    """Counts of orphaned broker records and Secrets removed during a prune pass."""

    agents: int = 0
    permission_sets: int = 0
    services: int = 0
    secrets: int = 0


@dataclass
class ReconcileSummary:
    services: int = 0
    permission_sets: int = 0
    agents: list[AgentSync] = field(default_factory=list)
    pruned: PruneSummary = field(default_factory=PruneSummary)


def reconcile(
    desired: DesiredState,
    aib: AIBAdminClient,
    secrets: SecretStore,
    secret_prefix: str = "kaos-aib",
    prune: bool = False,
    namespaces: tuple[str, ...] = (),
) -> ReconcileSummary:
    """Apply the desired AIB state and provision per-agent credential Secrets.

    Services and permission sets are created (or matched) first so their ids can be
    referenced; each agent is then created as a local AIB agent bound to its permission
    sets. Credentials are minted only when a Secret does not already carry them, keeping
    the pass idempotent and avoiding credential churn on every reconcile.

    When ``prune`` is set, KAOS-managed broker records and credential Secrets that are no
    longer in the desired state are removed in dependency-safe order (agents, then their
    credentials and Secrets, then permission sets, then services), restricted to the
    configured ``namespaces`` for Secret discovery.
    """
    summary = ReconcileSummary()

    service_ids: dict[str, str] = {}
    for service in desired.services:
        service_ids[service.client_id] = aib.create_or_get(
            "services", "client_id", service.client_id, service.admin_body()
        )
    summary.services = len(service_ids)

    permission_set_ids: dict[str, str] = {}
    for permission_set in desired.permission_sets:
        service_id = service_ids[permission_set.service_client_id]
        permission_set_ids[permission_set.name] = aib.create_or_get(
            "permission-sets", "name", permission_set.name, permission_set.admin_body(service_id)
        )
    summary.permission_sets = len(permission_set_ids)

    for agent in desired.agents:
        summary.agents.append(
            _reconcile_agent(agent, aib, secrets, secret_prefix, permission_set_ids)
        )

    if prune:
        summary.pruned = _prune(
            desired,
            aib,
            secrets,
            secret_prefix,
            namespaces,
            desired_client_ids=set(service_ids),
            desired_permission_set_names=set(permission_set_ids),
        )

    return summary


def _prune(
    desired: DesiredState,
    aib: AIBAdminClient,
    secrets: SecretStore,
    secret_prefix: str,
    namespaces: tuple[str, ...],
    desired_client_ids: set[str],
    desired_permission_set_names: set[str],
) -> PruneSummary:
    """Remove KAOS-managed broker records and Secrets absent from the desired state.

    Deletion follows dependency order so a record is never removed while another still
    references it: agents (and their credentials) first, then orphaned Secrets, then
    permission sets, then services. Only records KAOS owns -- identified by the projection
    encoding -- are considered, so externally-managed broker records are never touched.
    """
    pruned = PruneSummary()

    desired_external_ids = {agent.external_id for agent in desired.agents}
    for item in aib.list("agents"):
        display_name = item.get("display_name", "")
        if not is_kaos_agent_display_name(display_name):
            continue
        if display_name in desired_external_ids:
            continue
        aib.revoke_credentials(item["id"])
        if aib.delete("agents", item["id"]):
            pruned.agents += 1

    desired_secret_keys = {
        (agent.namespace, credential_secret_name(secret_prefix, agent.name))
        for agent in desired.agents
    }
    for namespace, name in secrets.list(namespaces):
        if (namespace, name) in desired_secret_keys:
            continue
        if secrets.delete(namespace, name):
            pruned.secrets += 1

    for item in aib.list("permission-sets"):
        name = item.get("name", "")
        if not is_kaos_permission_set_name(name):
            continue
        if name in desired_permission_set_names:
            continue
        if aib.delete("permission-sets", item["id"]):
            pruned.permission_sets += 1

    for item in aib.list("services"):
        client_id = item.get("client_id", "")
        if not is_kaos_service_client_id(client_id):
            continue
        if client_id in desired_client_ids:
            continue
        if aib.delete("services", item["id"]):
            pruned.services += 1

    return pruned


def _reconcile_agent(
    agent: DesiredAgent,
    aib: AIBAdminClient,
    secrets: SecretStore,
    secret_prefix: str,
    permission_set_ids: dict[str, str],
) -> AgentSync:
    bound = [permission_set_ids[name] for name in agent.permission_set_names]
    agent_id = aib.create_or_get(
        "agents", "display_name", agent.external_id, agent.admin_body(bound)
    )

    secret_name = credential_secret_name(secret_prefix, agent.name)
    existing = secrets.get(agent.namespace, secret_name)
    minted = False
    if not existing or not existing.get("client_id"):
        cred = aib.mint_credentials(agent_id)
        secrets.upsert(
            agent.namespace,
            secret_name,
            {"client_id": cred["client_id"], "client_secret": cred["client_secret"]},
        )
        minted = True

    return AgentSync(
        external_id=agent.external_id,
        agent_id=agent_id,
        secret_namespace=agent.namespace,
        secret_name=secret_name,
        credentials_minted=minted,
    )
