"""Entrypoint: event-driven reconcile loop projecting KAOS resources into AIB."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from kaos_sync.aib_client import AIBAdmin
from kaos_sync.config import Settings
from kaos_sync.observability import (
    HealthState,
    record_summary,
    setup_telemetry,
    start_health_server,
)
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


class DirtyTracker:
    """Thread-safe change signal set by watch events, consumed by the reconcile worker.

    Any number of watch threads call :meth:`mark_dirty`; the worker blocks in
    :meth:`wait_dirty` until a change arrives or the safety-net interval elapses. The
    flag is level-triggered and auto-clears on consumption, so a burst of events between
    two reconciles collapses into a single pass.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def mark_dirty(self) -> None:
        self._event.set()

    def wait_dirty(self, timeout: float) -> bool:
        """Block up to ``timeout`` seconds; return True if a change occurred, then clear."""
        flagged = self._event.wait(timeout)
        self._event.clear()
        return flagged


def reconcile_loop(
    settings: Settings,
    run_pass: Callable[[], None],
    dirty: DirtyTracker,
    *,
    should_continue: Callable[[], bool] = lambda: True,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run an initial reconcile, then reconcile on change (debounced) and on a safety-net.

    The worker reconciles when the watch marks the state dirty — after a short debounce to
    coalesce a burst of related changes — and at least every ``reconcile_interval_seconds``
    as a safety net even with no events. ``run_pass`` is expected to swallow its own
    transient errors so the loop stays alive.
    """
    run_pass()
    while should_continue():
        became_dirty = dirty.wait_dirty(settings.reconcile_interval_seconds)
        if became_dirty and settings.watch_debounce_seconds > 0:
            sleep(settings.watch_debounce_seconds)
            dirty.wait_dirty(0)  # consume events that arrived during the debounce window
        run_pass()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    setup_telemetry()

    from kaos_sync.k8s import (
        KaosResourceLister,
        KubeSecretStore,
        KubeWatchSource,
        load_kube_config,
    )

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
    start_health_server(settings.health_port, health)

    logger.info(
        "starting reconcile loop admin=%s interval=%ds namespaces=%s prune=%s health_port=%d "
        "watch=%s",
        settings.aib_admin_url,
        settings.reconcile_interval_seconds,
        ",".join(settings.namespaces) or "<all>",
        settings.prune_enabled,
        settings.health_port,
        settings.watch_enabled,
    )

    dirty = DirtyTracker()
    watch_source: "KubeWatchSource | None" = None
    if settings.watch_enabled:
        watch_source = KubeWatchSource(
            settings.namespaces,
            lambda event: dirty.mark_dirty(),
        )
        watch_source.start()

    def run_pass() -> None:
        try:
            summary = run_once(settings, lister, aib, secrets)
            record_summary(summary)
        except Exception:  # noqa: BLE001 - keep the loop alive across transient failures
            logger.exception("reconcile pass failed")
        finally:
            health.mark_ready()

    reconcile_loop(settings, run_pass, dirty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
