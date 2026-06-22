"""Tests for metrics recording and the health/readiness routing."""

from __future__ import annotations

from prometheus_client import REGISTRY

from kaos_sync.observability import HealthState, handle_path, record_summary
from kaos_sync.projection import project
from kaos_sync.reconcile import reconcile
from tests.test_reconcile import FakeAIB, FakeSecrets, _agent, _mcpserver


def test_healthz_is_always_ok():
    status, _, body = handle_path("/healthz", HealthState())
    assert status == 200
    assert body == b"ok"


def test_readyz_reflects_first_pass_completion():
    state = HealthState()
    assert handle_path("/readyz", state)[0] == 503
    state.mark_ready()
    assert handle_path("/readyz", state)[0] == 200


def test_metrics_endpoint_exposes_prometheus_text():
    status, content_type, body = handle_path("/metrics", HealthState())
    assert status == 200
    assert "text/plain" in content_type
    assert b"kaos_sync_reconcile_passes_total" in body


def test_unknown_path_is_404():
    assert handle_path("/nope", HealthState())[0] == 404


def test_query_string_is_ignored():
    assert handle_path("/healthz?verbose=1", HealthState())[0] == 200


def test_record_summary_updates_metrics():
    before = REGISTRY.get_sample_value("kaos_sync_reconcile_passes_total") or 0.0

    aib, secrets = FakeAIB(), FakeSecrets()
    summary = reconcile(project([_mcpserver("github"), _agent("a", ["github"])]), aib, secrets)
    record_summary(summary)

    after = REGISTRY.get_sample_value("kaos_sync_reconcile_passes_total")
    assert after == before + 1
    assert REGISTRY.get_sample_value("kaos_sync_agents_synced") == 1
    assert REGISTRY.get_sample_value("kaos_sync_last_pass_ok") == 1
    assert REGISTRY.get_sample_value("kaos_sync_services") == 1
