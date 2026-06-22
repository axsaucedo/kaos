"""OpenTelemetry metrics and health/readiness endpoints for the sync service.

Metrics are exported over OTLP (push) using the standard ``OTEL_*`` environment
variables, consistent with the rest of KAOS — there is no scrape endpoint. Counters
track cumulative reconcile activity (passes, mints, problems, prunes) and observable
gauges report the most recent pass snapshot. Liveness (``/healthz``) and readiness
(``/readyz``) are served over plain HTTP for the Kubernetes probes; readiness reports
that at least one reconcile pass has completed.

The path routing is factored into :func:`handle_path` so it can be unit tested without
binding a socket; :func:`start_health_server` wires that routing into a threaded HTTP
server for the runtime. Metric instruments live on :class:`SyncMetrics`, which binds to
a meter provider so tests can drive it with an in-memory reader.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable, Optional

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, MeterProvider, Observation

logger = logging.getLogger("kaos_sync")

_METER_NAME = "kaos-sync"
_PREFIX = "kaos.sync."


@dataclass
class _Snapshot:
    """Last-pass gauge values, replaced wholesale on each recorded pass."""

    services: int = 0
    permission_sets: int = 0
    agents_synced: int = 0
    agents_failed: int = 0
    last_pass_ok: int = 0


class SyncMetrics:
    """OTel instruments describing the reconcile loop, bound to a meter provider.

    Counters are cumulative; the last-pass values are reported through observable
    gauges that read the current :class:`_Snapshot` at collection time.
    """

    def __init__(self, meter_provider: Optional[MeterProvider] = None) -> None:
        meter = (meter_provider or metrics).get_meter(_METER_NAME)
        self._snapshot = _Snapshot()

        self._passes = meter.create_counter(
            _PREFIX + "reconcile.passes",
            unit="1",
            description="Total reconcile passes run.",
        )
        self._problems = meter.create_counter(
            _PREFIX + "reconcile.problems",
            unit="1",
            description="Reconcile problems encountered, by category.",
        )
        self._minted = meter.create_counter(
            _PREFIX + "credentials.minted",
            unit="1",
            description="Credential mints performed.",
        )
        self._pruned = meter.create_counter(
            _PREFIX + "pruned",
            unit="1",
            description="Orphaned records removed during pruning, by kind.",
        )
        self._conflicts = meter.create_counter(
            _PREFIX + "identity.conflicts",
            unit="1",
            description="Duplicate explicit security.id conflicts detected, by kind.",
        )

        for name, attr, description in (
            ("services", "services", "Broker services reconciled in the last pass."),
            (
                "permission_sets",
                "permission_sets",
                "Broker permission sets reconciled in the last pass.",
            ),
            ("agents.synced", "agents_synced", "Agents successfully synced in the last pass."),
            ("agents.failed", "agents_failed", "Agents that failed to sync in the last pass."),
            ("last_pass_ok", "last_pass_ok", "1 if the last pass had no problems, else 0."),
        ):
            meter.create_observable_gauge(
                _PREFIX + name,
                callbacks=[self._observe(attr)],
                unit="1",
                description=description,
            )

    def _observe(self, attr: str):
        def callback(_options: CallbackOptions) -> Iterable[Observation]:
            return [Observation(getattr(self._snapshot, attr))]

        return callback

    def record(self, summary) -> None:
        """Update instruments from a completed ``ReconcileSummary``."""
        self._passes.add(1)

        minted = sum(1 for agent in summary.agents if agent.credentials_minted)
        if minted:
            self._minted.add(minted)

        for problem in summary.problems:
            self._problems.add(1, {"category": problem.category.value})

        for kind in ("agents", "permission_sets", "services", "secrets"):
            count = getattr(summary.pruned, kind)
            if count:
                self._pruned.add(count, {"kind": kind})

        for conflict in getattr(summary, "conflicts", ()):
            self._conflicts.add(1, {"kind": conflict.kind})

        self._snapshot = _Snapshot(
            services=summary.services,
            permission_sets=summary.permission_sets,
            agents_synced=sum(1 for agent in summary.agents if agent.ok),
            agents_failed=sum(1 for agent in summary.agents if not agent.ok),
            last_pass_ok=1 if summary.ok else 0,
        )


_metrics: Optional[SyncMetrics] = None


def setup_telemetry() -> bool:
    """Configure OTLP metric export from the standard ``OTEL_*`` env vars.

    Mirrors the rest of KAOS: a no-op unless both ``OTEL_SERVICE_NAME`` and
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` are set. When unset, :func:`record_summary` still
    runs against the default no-op meter, so the reconcile loop is unaffected.
    """
    global _metrics
    if not os.getenv("OTEL_SERVICE_NAME") or not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        logger.debug(
            "OpenTelemetry not configured "
            "(OTEL_SERVICE_NAME and OTEL_EXPORTER_OTLP_ENDPOINT required); "
            "metrics export disabled"
        )
        return False

    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource

    resource = Resource.create({SERVICE_NAME: os.environ["OTEL_SERVICE_NAME"]})
    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    provider = SdkMeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _metrics = SyncMetrics(provider)
    logger.info(
        "OpenTelemetry metrics initialized (service=%s endpoint=%s)",
        os.environ["OTEL_SERVICE_NAME"],
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
    )
    return True


def record_summary(summary) -> None:
    """Record a completed reconcile pass into OTel metrics.

    Binds to the global meter provider on first use when telemetry was not explicitly
    configured, so instruments are valid (and harmlessly no-op) regardless of setup.
    """
    global _metrics
    if _metrics is None:
        _metrics = SyncMetrics()
    _metrics.record(summary)


@dataclass
class HealthState:
    """Shared liveness/readiness state updated by the reconcile loop."""

    ready: bool = False

    def mark_ready(self) -> None:
        self.ready = True


def handle_path(path: str, state: HealthState) -> tuple[int, str, bytes]:
    """Resolve an HTTP path to ``(status, content_type, body)`` for the health server."""
    route = path.split("?", 1)[0]
    if route == "/healthz":
        return 200, "text/plain", b"ok"
    if route == "/readyz":
        if state.ready:
            return 200, "text/plain", b"ready"
        return 503, "text/plain", b"not ready"
    return 404, "text/plain", b"not found"


def _make_handler(state: HealthState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            status, content_type, body = handle_path(self.path, state)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - match base API
            return

    return _Handler


def start_health_server(port: int, state: HealthState) -> ThreadingHTTPServer:
    """Start a daemon HTTP server serving ``/healthz`` and ``/readyz`` on ``port``."""
    server = ThreadingHTTPServer(("", port), _make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
