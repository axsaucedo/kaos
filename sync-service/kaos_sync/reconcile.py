"""Reconciliation of desired AIB state and per-agent credential Secrets.

This module is I/O-free in itself: it orchestrates an :class:`AIBAdminClient` and a
:class:`SecretStore` (both protocols) so it can be unit tested with fakes. Concrete
implementations live in :mod:`kaos_sync.aib_client` and :mod:`kaos_sync.secrets`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kaos_sync.projection import DesiredAgent, DesiredState


def credential_secret_name(prefix: str, agent_name: str) -> str:
    """Per-agent credential Secret name, derivable by both the sync service and operator."""
    return f"{prefix}-{agent_name}"


class AIBAdminClient(Protocol):
    def create_or_get(
        self, collection: str, match_field: str, match_value: str, body: dict
    ) -> str: ...

    def mint_credentials(self, agent_id: str) -> dict: ...


class SecretStore(Protocol):
    def get(self, namespace: str, name: str) -> dict[str, str] | None: ...

    def upsert(self, namespace: str, name: str, string_data: dict[str, str]) -> None: ...


@dataclass
class AgentSync:
    """Outcome of reconciling a single agent."""

    external_id: str
    agent_id: str
    secret_namespace: str
    secret_name: str
    credentials_minted: bool


@dataclass
class ReconcileSummary:
    services: int = 0
    permission_sets: int = 0
    agents: list[AgentSync] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.agents is None:
            self.agents = []


def reconcile(
    desired: DesiredState,
    aib: AIBAdminClient,
    secrets: SecretStore,
    secret_prefix: str = "kaos-aib",
) -> ReconcileSummary:
    """Apply the desired AIB state and provision per-agent credential Secrets.

    Services and permission sets are created (or matched) first so their ids can be
    referenced; each agent is then created as a local AIB agent bound to its permission
    sets. Credentials are minted only when a Secret does not already carry them, keeping
    the pass idempotent and avoiding credential churn on every reconcile.
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

    return summary


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
