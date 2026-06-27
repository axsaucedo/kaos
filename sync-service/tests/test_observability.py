"""Tests for OTel metrics recording and the health/readiness routing."""

from __future__ import annotations

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from kaos_sync.observability import HealthState, SyncMetrics, handle_path
from kaos_sync.projection import project
from kaos_sync.reconcile import reconcile
from tests.test_reconcile import FakeAIB, FakeSecrets, _agent, _mcpserver


def _collect(reader: InMemoryMetricReader) -> dict[str, float]:
    """Flatten the latest metric export into ``{metric_name: summed_value}``."""
    values: dict[str, float] = {}
    data = reader.get_metrics_data()
    if data is None:
        return values
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                values[metric.name] = sum(
                    getattr(point, "value", 0) for point in metric.data.data_points
                )
    return values


def _metrics_with_reader() -> tuple[SyncMetrics, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    return SyncMetrics(provider), reader


def test_healthz_is_always_ok():
    status, _, body = handle_path("/healthz", HealthState())
    assert status == 200
    assert body == b"ok"


def test_readyz_reflects_first_pass_completion():
    state = HealthState()
    assert handle_path("/readyz", state)[0] == 503
    state.mark_ready()
    assert handle_path("/readyz", state)[0] == 200


def test_metrics_route_is_not_served_over_http():
    # Metrics are pushed via OTLP, not scraped; /metrics must not be a route.
    assert handle_path("/metrics", HealthState())[0] == 404


def test_unknown_path_is_404():
    assert handle_path("/nope", HealthState())[0] == 404


def test_query_string_is_ignored():
    assert handle_path("/healthz?verbose=1", HealthState())[0] == 200


def test_record_updates_counters_and_gauges():
    sync_metrics, reader = _metrics_with_reader()

    summary = reconcile(
        project([_mcpserver("github"), _agent("a", ["github"])]), FakeAIB(), FakeSecrets()
    )
    sync_metrics.record(summary)

    values = _collect(reader)
    assert values["kaos.sync.reconcile.passes"] == 1
    assert values["kaos.sync.services"] == 1
    assert values["kaos.sync.agents.synced"] == 1
    assert values["kaos.sync.last_pass_ok"] == 1


def test_counters_accumulate_across_passes():
    sync_metrics, reader = _metrics_with_reader()

    desired = project([_mcpserver("github"), _agent("a", ["github"])])
    sync_metrics.record(reconcile(desired, FakeAIB(), FakeSecrets()))
    sync_metrics.record(reconcile(desired, FakeAIB(), FakeSecrets()))

    values = _collect(reader)
    assert values["kaos.sync.reconcile.passes"] == 2
