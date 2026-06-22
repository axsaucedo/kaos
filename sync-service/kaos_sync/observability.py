"""Prometheus metrics and health/readiness endpoints for the sync service.

Metrics describe the most recent reconcile pass (counts, failures, prune activity) and
are exposed on ``/metrics``. Liveness (``/healthz``) reports that the process is up;
readiness (``/readyz``) reports that at least one reconcile pass has completed, so a
deployment is only considered ready once it has projected the current desired state.

The path routing is factored into :func:`handle_path` so it can be unit tested without
binding a socket; :func:`start_http_servers` wires that routing into a threaded HTTP
server for the runtime.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

RECONCILE_PASSES = Counter("kaos_sync_reconcile_passes_total", "Total reconcile passes run.")
RECONCILE_PROBLEMS = Counter(
    "kaos_sync_reconcile_problems_total",
    "Reconcile problems encountered, by category.",
    ["category"],
)
CREDENTIALS_MINTED = Counter("kaos_sync_credentials_minted_total", "Credential mints performed.")
PRUNED = Counter(
    "kaos_sync_pruned_total", "Orphaned records removed during pruning, by kind.", ["kind"]
)
SERVICES_SYNCED = Gauge("kaos_sync_services", "Broker services reconciled in the last pass.")
PERMISSION_SETS_SYNCED = Gauge(
    "kaos_sync_permission_sets", "Broker permission sets reconciled in the last pass."
)
AGENTS_SYNCED = Gauge("kaos_sync_agents_synced", "Agents successfully synced in the last pass.")
AGENTS_FAILED = Gauge("kaos_sync_agents_failed", "Agents that failed to sync in the last pass.")
LAST_PASS_OK = Gauge(
    "kaos_sync_last_pass_ok", "1 if the last reconcile pass had no problems, else 0."
)


def record_summary(summary) -> None:
    """Update metrics from a completed :class:`~kaos_sync.reconcile.ReconcileSummary`."""
    RECONCILE_PASSES.inc()
    minted = sum(1 for agent in summary.agents if agent.credentials_minted)
    if minted:
        CREDENTIALS_MINTED.inc(minted)
    for problem in summary.problems:
        RECONCILE_PROBLEMS.labels(category=problem.category.value).inc()
    if summary.pruned.agents:
        PRUNED.labels(kind="agents").inc(summary.pruned.agents)
    if summary.pruned.permission_sets:
        PRUNED.labels(kind="permission_sets").inc(summary.pruned.permission_sets)
    if summary.pruned.services:
        PRUNED.labels(kind="services").inc(summary.pruned.services)
    if summary.pruned.secrets:
        PRUNED.labels(kind="secrets").inc(summary.pruned.secrets)
    SERVICES_SYNCED.set(summary.services)
    PERMISSION_SETS_SYNCED.set(summary.permission_sets)
    AGENTS_SYNCED.set(sum(1 for agent in summary.agents if agent.ok))
    AGENTS_FAILED.set(sum(1 for agent in summary.agents if not agent.ok))
    LAST_PASS_OK.set(1 if summary.ok else 0)


@dataclass
class HealthState:
    """Shared liveness/readiness state updated by the reconcile loop."""

    ready: bool = False

    def mark_ready(self) -> None:
        self.ready = True


def handle_path(path: str, state: HealthState) -> tuple[int, str, bytes]:
    """Resolve an HTTP path to ``(status, content_type, body)`` for the health server."""
    route = path.split("?", 1)[0]
    if route == "/metrics":
        return 200, CONTENT_TYPE_LATEST, generate_latest()
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


def start_http_servers(ports: tuple[int, ...], state: HealthState) -> list[ThreadingHTTPServer]:
    """Start a daemon HTTP server on each distinct port serving the health routes.

    The metrics and health ports are commonly the same; identical ports are de-duplicated
    so a single server backs every route. Each server runs on a daemon thread so it never
    blocks process shutdown.
    """
    handler = _make_handler(state)
    servers: list[ThreadingHTTPServer] = []
    for port in dict.fromkeys(ports):
        server = ThreadingHTTPServer(("", port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
    return servers
