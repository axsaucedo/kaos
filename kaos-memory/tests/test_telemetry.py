"""Unit coverage for the memory-service OpenTelemetry bootstrap.

Focuses on the parity behaviours with the agent runtime: the OTLP exporter is
constructed env-driven (no explicit endpoint), logs are exported with trace
correlation, and outbound HTTPX tracing is opt-in. The heavier span-emission
path is covered by ``test_service_e2e``; here we avoid mutating the process
tracer provider by patching the exporter/provider seams.
"""

import logging

import kaos_memory.telemetry as telemetry


def test_getenv_bool_parses_truthy_and_falsy(monkeypatch):
    monkeypatch.setenv("FLAG", "yes")
    assert telemetry._getenv_bool("FLAG") is True
    monkeypatch.setenv("FLAG", "0")
    assert telemetry._getenv_bool("FLAG") is False
    monkeypatch.delenv("FLAG", raising=False)
    assert telemetry._getenv_bool("FLAG", default=True) is True


def test_log_level_int_defaults_to_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert telemetry._log_level_int() == logging.INFO
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert telemetry._log_level_int() == logging.DEBUG


def test_setup_telemetry_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    reached = {"setup": False}
    monkeypatch.setattr(
        telemetry, "_setup_log_export", lambda resource: reached.__setitem__("setup", True)
    )

    telemetry.setup_telemetry(object())
    assert reached["setup"] is False


def test_setup_telemetry_noop_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry.setup_telemetry(object())  # must not raise


def test_span_exporter_is_env_driven(monkeypatch):
    """The exporter is constructed with no explicit endpoint so the SDK reads
    the full OTEL_EXPORTER_OTLP_* env surface, matching the agent runtime."""

    captured = {}

    class _FakeExporter:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def shutdown(self, *args, **kwargs):
            pass

        def force_flush(self, *args, **kwargs):
            return True

        def export(self, *args, **kwargs):
            return None

    import opentelemetry.exporter.otlp.proto.grpc.trace_exporter as span_mod
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry import trace

    monkeypatch.setattr(span_mod, "OTLPSpanExporter", _FakeExporter)
    monkeypatch.setattr(trace, "set_tracer_provider", lambda provider: None)
    monkeypatch.setattr(FastAPIInstrumentor, "instrument_app", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(telemetry, "_setup_log_export", lambda resource: None)
    monkeypatch.setattr(telemetry, "_setup_httpx_instrumentation", lambda: None)

    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "kaos-memory-test")

    telemetry.setup_telemetry(object())

    assert captured["args"] == ()
    assert "endpoint" not in captured["kwargs"]


def test_httpx_instrumentation_is_opt_in(monkeypatch):
    calls = {"instrumented": 0}

    class _FakeInstrumentor:
        def instrument(self):
            calls["instrumented"] += 1

    import opentelemetry.instrumentation.httpx as httpx_mod

    monkeypatch.setattr(httpx_mod, "HTTPXClientInstrumentor", _FakeInstrumentor)

    monkeypatch.delenv("OTEL_INCLUDE_HTTP_CLIENT", raising=False)
    telemetry._setup_httpx_instrumentation()
    assert calls["instrumented"] == 0

    monkeypatch.setenv("OTEL_INCLUDE_HTTP_CLIENT", "true")
    telemetry._setup_httpx_instrumentation()
    assert calls["instrumented"] == 1
