"""Entrypoint: periodic reconcile loop projecting KAOS resources into AIB."""

from __future__ import annotations

import logging
import time

from kaos_sync.aib_client import AIBAdmin
from kaos_sync.config import Settings
from kaos_sync.observability import HealthState, record_summary, start_http_servers
from kaos_sync.projection import project
from kaos_sync.reconcile import ReconcileSummary, reconcile

logger = logging.getLogger("kaos_sync")


def run_once(settings: Settings, lister, aib, secrets) -> ReconcileSummary:
    """Run a single reconcile pass and return its summary."""
    resources = lister.list_resources(settings.namespaces)
    desired = project(resources)
    summary = reconcile(
        desired,
        aib,
        secrets,
        settings.credential_secret_prefix,
        prune=settings.prune_enabled,
        namespaces=settings.namespaces,
    )
    minted = sum(1 for a in summary.agents if a.credentials_minted)
    failed = sum(1 for a in summary.agents if not a.ok)
    logger.info(
        "reconciled services=%d permission_sets=%d agents=%d credentials_minted=%d "
        "failed=%d pruned_agents=%d pruned_permission_sets=%d pruned_services=%d "
        "pruned_secrets=%d problems=%d",
        summary.services,
        summary.permission_sets,
        len(summary.agents),
        minted,
        failed,
        summary.pruned.agents,
        summary.pruned.permission_sets,
        summary.pruned.services,
        summary.pruned.secrets,
        len(summary.problems),
    )
    for problem in summary.problems:
        logger.warning(
            "problem category=%s resource=%s detail=%s",
            problem.category.value,
            problem.resource,
            problem.detail,
        )
    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()

    from kaos_sync.k8s import KaosResourceLister, KubeSecretStore, load_kube_config

    load_kube_config()
    lister = KaosResourceLister()
    secrets = KubeSecretStore()
    aib = AIBAdmin(
        base_url=settings.aib_admin_url,
        principal=settings.aib_principal,
        principal_header=settings.aib_principal_header,
        timeout=settings.request_timeout_seconds,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_delay_seconds=settings.retry_base_delay_seconds,
    )

    health = HealthState()
    start_http_servers((settings.metrics_port, settings.health_port), health)

    logger.info(
        "starting reconcile loop admin=%s interval=%ds namespaces=%s "
        "prune=%s metrics_port=%d health_port=%d",
        settings.aib_admin_url,
        settings.reconcile_interval_seconds,
        ",".join(settings.namespaces) or "<all>",
        settings.prune_enabled,
        settings.metrics_port,
        settings.health_port,
    )
    while True:
        try:
            summary = run_once(settings, lister, aib, secrets)
            record_summary(summary)
        except Exception:  # noqa: BLE001 - keep the loop alive across transient failures
            logger.exception("reconcile pass failed")
        finally:
            health.mark_ready()
        time.sleep(settings.reconcile_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
