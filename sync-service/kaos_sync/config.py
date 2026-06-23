"""Runtime configuration for the KAOS sync service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Settings sourced from the environment.

    aib_admin_url: base URL of the AIB admin API (including the ``/api`` suffix).
    aib_principal: principal sent in the pre-auth header to the AIB admin API.
    aib_principal_header: header carrying the pre-authenticated principal.
    namespaces: namespaces to watch; empty means cluster-wide.
    credential_secret_prefix: prefix for per-agent credential Secret names.
    reconcile_interval_seconds: delay between reconcile passes.
    request_timeout_seconds: per-request timeout for AIB admin calls.
    prune_enabled: whether to delete orphaned broker records and Secrets each pass.
    health_port: port exposing ``/healthz`` and ``/readyz`` for the Kubernetes probes.
    retry_max_attempts: max attempts per AIB admin request before giving up.
    retry_base_delay_seconds: base delay for exponential backoff between retries.
    watch_enabled: react to KAOS resource changes via a watch (default on); when off the
        service runs a pure fixed-interval poll loop.
    watch_debounce_seconds: window to coalesce a burst of watch events into one reconcile.
    leader_election_enabled: contend for a Lease so only one replica reconciles (default
        on); a single replica simply always wins. Disable for the simplest single-pod dev.
    leader_lease_name: name of the coordination.k8s.io Lease used for election.
    leader_namespace: namespace holding the Lease (defaults to the service namespace).
    leader_identity: holder identity recorded on the Lease; defaults to POD_NAME/hostname.
    leader_lease_duration_seconds: duration a leader holds the Lease before it can be stolen.
    leader_renew_deadline_seconds: deadline within which the leader must renew or step down.
    leader_retry_period_seconds: interval between acquire/renew attempts.

    Metrics are exported via OTLP using the standard ``OTEL_*`` environment variables
    (e.g. ``OTEL_SERVICE_NAME``, ``OTEL_EXPORTER_OTLP_ENDPOINT``), read by the SDK
    directly, so there is no scrape port to configure here.
    """

    aib_admin_url: str = "http://localhost:14000/api"
    aib_principal: str = "kaos-sync"
    aib_principal_header: str = "X-Remote-User"
    namespaces: tuple[str, ...] = ()
    credential_secret_prefix: str = "kaos-aib"
    reconcile_interval_seconds: int = 30
    request_timeout_seconds: float = 10.0
    prune_enabled: bool = True
    health_port: int = 8080
    retry_max_attempts: int = 4
    retry_base_delay_seconds: float = 0.5
    watch_enabled: bool = True
    watch_debounce_seconds: float = 1.0
    leader_election_enabled: bool = True
    leader_lease_name: str = "kaos-sync-leader"
    leader_namespace: str = "kaos-system"
    leader_identity: str = ""
    leader_lease_duration_seconds: float = 15.0
    leader_renew_deadline_seconds: float = 10.0
    leader_retry_period_seconds: float = 2.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        namespaces = tuple(
            n.strip() for n in env.get("KAOS_SYNC_NAMESPACES", "").split(",") if n.strip()
        )
        return cls(
            aib_admin_url=env.get("AIB_ADMIN_URL", cls.aib_admin_url),
            aib_principal=env.get("AIB_PRINCIPAL", cls.aib_principal),
            aib_principal_header=env.get("AIB_PRINCIPAL_HEADER", cls.aib_principal_header),
            namespaces=namespaces,
            credential_secret_prefix=env.get(
                "KAOS_SYNC_CREDENTIAL_SECRET_PREFIX", cls.credential_secret_prefix
            ),
            reconcile_interval_seconds=int(
                env.get("KAOS_SYNC_RECONCILE_INTERVAL_SECONDS", cls.reconcile_interval_seconds)
            ),
            request_timeout_seconds=float(
                env.get("KAOS_SYNC_REQUEST_TIMEOUT_SECONDS", cls.request_timeout_seconds)
            ),
            prune_enabled=_env_bool(env, "KAOS_SYNC_PRUNE_ENABLED", cls.prune_enabled),
            health_port=int(env.get("KAOS_SYNC_HEALTH_PORT", cls.health_port)),
            retry_max_attempts=int(env.get("KAOS_SYNC_RETRY_MAX_ATTEMPTS", cls.retry_max_attempts)),
            retry_base_delay_seconds=float(
                env.get("KAOS_SYNC_RETRY_BASE_DELAY_SECONDS", cls.retry_base_delay_seconds)
            ),
            watch_enabled=_env_bool(env, "KAOS_SYNC_WATCH_ENABLED", cls.watch_enabled),
            watch_debounce_seconds=float(
                env.get("KAOS_SYNC_WATCH_DEBOUNCE_SECONDS", cls.watch_debounce_seconds)
            ),
            leader_election_enabled=_env_bool(
                env, "KAOS_SYNC_LEADER_ELECTION_ENABLED", cls.leader_election_enabled
            ),
            leader_lease_name=env.get("KAOS_SYNC_LEADER_LEASE_NAME", cls.leader_lease_name),
            leader_namespace=env.get(
                "KAOS_SYNC_LEADER_NAMESPACE",
                env.get("POD_NAMESPACE", cls.leader_namespace),
            ),
            leader_identity=env.get(
                "KAOS_SYNC_LEADER_IDENTITY",
                env.get("POD_NAME", ""),
            ),
            leader_lease_duration_seconds=float(
                env.get(
                    "KAOS_SYNC_LEADER_LEASE_DURATION_SECONDS",
                    cls.leader_lease_duration_seconds,
                )
            ),
            leader_renew_deadline_seconds=float(
                env.get(
                    "KAOS_SYNC_LEADER_RENEW_DEADLINE_SECONDS",
                    cls.leader_renew_deadline_seconds,
                )
            ),
            leader_retry_period_seconds=float(
                env.get(
                    "KAOS_SYNC_LEADER_RETRY_PERIOD_SECONDS",
                    cls.leader_retry_period_seconds,
                )
            ),
        )


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
