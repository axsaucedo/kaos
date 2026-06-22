"""Reconciliation of desired AIB state and per-agent credential Secrets.

This module is I/O-free in itself: it orchestrates an :class:`AIBAdminClient` and a
:class:`SecretStore` (both protocols) so it can be unit tested with fakes. Concrete
implementations live in :mod:`kaos_sync.aib_client` and :mod:`kaos_sync.secrets`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Protocol

from kaos_sync.projection import (
    DesiredAgent,
    DesiredState,
    IdentityConflict,
    is_kaos_agent_display_name,
    is_kaos_permission_set_name,
    is_kaos_service_client_id,
    is_valid_agent_external_id,
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


class ProblemCategory(str, Enum):
    """Classification of a reconcile problem, for status reporting and alerting."""

    AIB_UNREACHABLE = "aib_unreachable"
    MISSING_CREDENTIALS = "missing_credentials"
    UNSUPPORTED_EDGE = "unsupported_edge"
    STALE_EXTERNAL_ID = "stale_external_id"
    PRUNE_FAILED = "prune_failed"


@dataclass
class Problem:
    """A single non-fatal issue encountered while reconciling one resource."""

    category: ProblemCategory
    resource: str
    detail: str


@dataclass
class AgentSync:
    """Outcome of reconciling a single agent."""

    external_id: str
    agent_id: str
    secret_namespace: str
    secret_name: str
    credentials_minted: bool
    ok: bool = True
    error: str | None = None


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
    problems: list[Problem] = field(default_factory=list)
    conflicts: list[IdentityConflict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the pass completed with no recorded problems."""
        return not self.problems


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

    Reconciliation is isolated per resource: a failure on one service, permission set or
    agent is recorded as a :class:`Problem` and does not prevent the remaining resources
    from being reconciled, so a single broker hiccup or malformed resource cannot stall
    the whole fleet. Agents whose permission sets could not be created are skipped fail
    closed (no credentials are minted for an unauthorized agent).

    When ``prune`` is set, KAOS-managed broker records and credential Secrets that are no
    longer in the desired state are removed in dependency-safe order (agents, then their
    credentials and Secrets, then permission sets, then services), restricted to the
    configured ``namespaces`` for Secret discovery.
    """
    summary = ReconcileSummary()
    summary.conflicts = list(desired.conflicts)

    service_ids: dict[str, str] = {}
    for service in desired.services:
        try:
            service_ids[service.client_id] = aib.create_or_get(
                "services", "client_id", service.client_id, service.admin_body()
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-resource failures
            summary.problems.append(
                Problem(ProblemCategory.AIB_UNREACHABLE, f"service {service.client_id}", str(exc))
            )
    summary.services = len(service_ids)

    permission_set_ids: dict[str, str] = {}
    for permission_set in desired.permission_sets:
        if permission_set.service_client_id not in service_ids:
            summary.problems.append(
                Problem(
                    ProblemCategory.UNSUPPORTED_EDGE,
                    f"permission-set {permission_set.name}",
                    f"service {permission_set.service_client_id} unavailable",
                )
            )
            continue
        service_id = service_ids[permission_set.service_client_id]
        try:
            permission_set_ids[permission_set.name] = aib.create_or_get(
                "permission-sets",
                "name",
                permission_set.name,
                permission_set.admin_body(service_id),
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-resource failures
            summary.problems.append(
                Problem(
                    ProblemCategory.AIB_UNREACHABLE,
                    f"permission-set {permission_set.name}",
                    str(exc),
                )
            )
    summary.permission_sets = len(permission_set_ids)

    for agent in desired.agents:
        summary.agents.append(
            _reconcile_agent(
                agent, aib, secrets, secret_prefix, permission_set_ids, summary.problems
            )
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
            problems=summary.problems,
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
    problems: list[Problem],
) -> PruneSummary:
    """Remove KAOS-managed broker records and Secrets absent from the desired state.

    Deletion follows dependency order so a record is never removed while another still
    references it: agents (and their credentials) first, then orphaned Secrets, then
    permission sets, then services. Only records KAOS owns -- identified by the projection
    encoding -- are considered, so externally-managed broker records are never touched. A
    failed deletion is recorded as a :class:`Problem` and never aborts the rest of the
    prune pass.
    """
    pruned = PruneSummary()

    desired_external_ids = {agent.external_id for agent in desired.agents}
    for item in _safe_list(aib, "agents", problems):
        display_name = item.get("display_name", "")
        if not is_kaos_agent_display_name(display_name):
            continue
        if display_name in desired_external_ids:
            continue
        if not is_valid_agent_external_id(display_name):
            problems.append(
                Problem(
                    ProblemCategory.STALE_EXTERNAL_ID,
                    f"agent {item.get('id', '?')}",
                    f"malformed external id {display_name!r}; skipping deletion",
                )
            )
            continue
        try:
            aib.revoke_credentials(item["id"])
            if aib.delete("agents", item["id"]):
                pruned.agents += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-resource prune failures
            problems.append(Problem(ProblemCategory.PRUNE_FAILED, f"agent {item['id']}", str(exc)))

    desired_secret_keys = {
        (agent.namespace, credential_secret_name(secret_prefix, agent.name))
        for agent in desired.agents
    }
    try:
        managed_secrets = secrets.list(namespaces)
    except Exception as exc:  # noqa: BLE001 - isolate secret listing failures
        problems.append(Problem(ProblemCategory.PRUNE_FAILED, "secrets", str(exc)))
        managed_secrets = []
    for namespace, name in managed_secrets:
        if (namespace, name) in desired_secret_keys:
            continue
        try:
            if secrets.delete(namespace, name):
                pruned.secrets += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-resource prune failures
            problems.append(
                Problem(ProblemCategory.PRUNE_FAILED, f"secret {namespace}/{name}", str(exc))
            )

    for item in _safe_list(aib, "permission-sets", problems):
        name = item.get("name", "")
        if not is_kaos_permission_set_name(name):
            continue
        if name in desired_permission_set_names:
            continue
        try:
            if aib.delete("permission-sets", item["id"]):
                pruned.permission_sets += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-resource prune failures
            problems.append(
                Problem(ProblemCategory.PRUNE_FAILED, f"permission-set {item['id']}", str(exc))
            )

    for item in _safe_list(aib, "services", problems):
        client_id = item.get("client_id", "")
        if not is_kaos_service_client_id(client_id):
            continue
        if client_id in desired_client_ids:
            continue
        try:
            if aib.delete("services", item["id"]):
                pruned.services += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-resource prune failures
            problems.append(
                Problem(ProblemCategory.PRUNE_FAILED, f"service {item['id']}", str(exc))
            )

    return pruned


def _safe_list(aib: AIBAdminClient, collection: str, problems: list[Problem]) -> list[dict]:
    """List a broker collection, recording unreachability instead of raising."""
    try:
        return aib.list(collection)
    except Exception as exc:  # noqa: BLE001 - isolate broker listing failures
        problems.append(Problem(ProblemCategory.AIB_UNREACHABLE, f"list {collection}", str(exc)))
        return []


def _reconcile_agent(
    agent: DesiredAgent,
    aib: AIBAdminClient,
    secrets: SecretStore,
    secret_prefix: str,
    permission_set_ids: dict[str, str],
    problems: list[Problem],
) -> AgentSync:
    secret_name = credential_secret_name(secret_prefix, agent.name)
    resource = f"agent {agent.namespace}/{agent.name}"

    missing = [name for name in agent.permission_set_names if name not in permission_set_ids]
    if missing:
        detail = f"permission sets unavailable: {', '.join(missing)}"
        problems.append(Problem(ProblemCategory.UNSUPPORTED_EDGE, resource, detail))
        return AgentSync(agent.external_id, "", agent.namespace, secret_name, False, False, detail)

    bound = [permission_set_ids[name] for name in agent.permission_set_names]
    try:
        agent_id = aib.create_or_get(
            "agents", "display_name", agent.external_id, agent.admin_body(bound)
        )
    except Exception as exc:  # noqa: BLE001 - isolate per-resource failures
        problems.append(Problem(ProblemCategory.AIB_UNREACHABLE, resource, str(exc)))
        return AgentSync(
            agent.external_id, "", agent.namespace, secret_name, False, False, str(exc)
        )

    try:
        existing = secrets.get(agent.namespace, secret_name)
        minted = False
        if not existing or not existing.get("client_id"):
            cred = aib.mint_credentials(agent_id)
            if not cred.get("client_id") or not cred.get("client_secret"):
                raise RuntimeError("broker returned incomplete credentials")
            secrets.upsert(
                agent.namespace,
                secret_name,
                {"client_id": cred["client_id"], "client_secret": cred["client_secret"]},
            )
            minted = True
    except Exception as exc:  # noqa: BLE001 - isolate per-resource failures
        problems.append(Problem(ProblemCategory.MISSING_CREDENTIALS, resource, str(exc)))
        return AgentSync(
            agent.external_id, agent_id, agent.namespace, secret_name, False, False, str(exc)
        )

    return AgentSync(
        external_id=agent.external_id,
        agent_id=agent_id,
        secret_namespace=agent.namespace,
        secret_name=secret_name,
        credentials_minted=minted,
    )
