"""Entrypoint: event-driven reconcile loop projecting KAOS resources into AIB."""

from __future__ import annotations

import logging
import socket
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
        credential_rotation_seconds=settings.credential_rotation_seconds,
    )
    minted = sum(1 for a in summary.agents if a.credentials_minted)
    rotated = sum(1 for a in summary.agents if a.credentials_rotated)
    failed = sum(1 for a in summary.agents if not a.ok)
    logger.info(
        "reconciled services=%d permission_sets=%d agents=%d credentials_minted=%d "
        "credentials_rotated=%d failed=%d pruned_agents=%d pruned_permission_sets=%d "
        "pruned_services=%d pruned_secrets=%d problems=%d",
        summary.services,
        summary.permission_sets,
        len(summary.agents),
        minted,
        rotated,
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


class LeaderElector:
    """Single-active election: invoke callbacks as leadership is gained and lost.

    Each retry period the backend is asked to acquire-or-renew the Lease. A False -> True
    transition fires ``on_started_leading`` (start reconciling); a True -> False transition
    — whether another replica took over or the backend errored — fires
    ``on_stopped_leading`` (stop reconciling and stand by, still re-contending). The loop
    itself never raises on a backend error; it treats it as "not leading" and retries.
    """

    def __init__(
        self,
        backend,
        *,
        on_started_leading: Callable[[], None],
        on_stopped_leading: Callable[[], None],
        retry_period_seconds: float,
        should_continue: Callable[[], bool] = lambda: True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._backend = backend
        self._on_started_leading = on_started_leading
        self._on_stopped_leading = on_stopped_leading
        self._retry_period_seconds = retry_period_seconds
        self._should_continue = should_continue
        self._sleep = sleep

    def run(self) -> None:
        leading = False
        while self._should_continue():
            try:
                acquired = self._backend.try_acquire_or_renew()
            except Exception:  # noqa: BLE001 - a backend error must not crash election
                logger.warning(
                    "leader election backend error; treating as not leading", exc_info=True
                )
                acquired = False
            if acquired and not leading:
                leading = True
                logger.info("acquired leadership")
                self._on_started_leading()
            elif not acquired and leading:
                leading = False
                logger.info("lost leadership; standing by")
                self._on_stopped_leading()
            self._sleep(self._retry_period_seconds)


class _WorkerHandle:
    """Starts/stops the watch + reconcile worker so the leader runs it and a standby does not."""

    def __init__(self, settings: Settings, run_pass: Callable[[], None]) -> None:
        self._settings = settings
        self._run_pass = run_pass
        self._active = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._watch_source = None
        self._dirty: "DirtyTracker | None" = None

    def start(self) -> None:
        from kaos_sync.k8s import KubeWatchSource

        self._active.set()
        self._dirty = DirtyTracker()
        if self._settings.watch_enabled:
            self._watch_source = KubeWatchSource(
                self._settings.namespaces,
                lambda event: self._dirty.mark_dirty(),  # type: ignore[union-attr]
            )
            self._watch_source.start()
        self._thread = threading.Thread(
            target=reconcile_loop,
            args=(self._settings, self._guarded_run_pass, self._dirty),
            kwargs={"should_continue": self._active.is_set},
            name="reconcile-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._active.clear()
        if self._watch_source is not None:
            self._watch_source.stop()
            self._watch_source = None
        if self._dirty is not None:
            self._dirty.mark_dirty()  # wake the worker so it observes should_continue() is False
        if self._thread is not None:
            self._thread.join(timeout=self._settings.reconcile_interval_seconds + 5)
            self._thread = None

    def _guarded_run_pass(self) -> None:
        # Never mint/prune after leadership is relinquished, even for an in-flight loop turn.
        if self._active.is_set():
            self._run_pass()


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
    health.mark_ready()  # the process is healthy regardless of leadership (a standby is ready)

    logger.info(
        "starting reconcile loop admin=%s interval=%ds namespaces=%s prune=%s health_port=%d "
        "watch=%s leader_election=%s",
        settings.aib_admin_url,
        settings.reconcile_interval_seconds,
        ",".join(settings.namespaces) or "<all>",
        settings.prune_enabled,
        settings.health_port,
        settings.watch_enabled,
        settings.leader_election_enabled,
    )

    def run_pass() -> None:
        try:
            summary = run_once(settings, lister, aib, secrets)
            record_summary(summary)
        except Exception:  # noqa: BLE001 - keep the loop alive across transient failures
            logger.exception("reconcile pass failed")
        finally:
            health.mark_ready()

    if not settings.leader_election_enabled:
        dirty = DirtyTracker()
        if settings.watch_enabled:
            watch_source = KubeWatchSource(settings.namespaces, lambda event: dirty.mark_dirty())
            watch_source.start()
        reconcile_loop(settings, run_pass, dirty)
        return 0

    from kaos_sync.k8s import KubeLeaseBackend

    identity = settings.leader_identity or socket.gethostname()
    backend = KubeLeaseBackend(
        name=settings.leader_lease_name,
        namespace=settings.leader_namespace,
        identity=identity,
        lease_duration_seconds=settings.leader_lease_duration_seconds,
    )
    worker = _WorkerHandle(settings, run_pass)
    elector = LeaderElector(
        backend,
        on_started_leading=worker.start,
        on_stopped_leading=worker.stop,
        retry_period_seconds=settings.leader_retry_period_seconds,
    )
    logger.info(
        "contending for leadership lease=%s/%s identity=%s",
        settings.leader_namespace,
        settings.leader_lease_name,
        identity,
    )
    elector.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
