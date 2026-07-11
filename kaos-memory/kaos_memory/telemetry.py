"""OpenTelemetry bootstrap for the memory service.

The service emits spans via ``trace.get_tracer("kaos.memory")`` regardless of
configuration; those spans are dropped by the default no-op provider unless a
real ``TracerProvider`` with an OTLP exporter is installed. ``setup_telemetry``
installs one — and instruments the FastAPI app — only when an OTLP endpoint is
configured and the SDK is not explicitly disabled, so the service stays cheap
when telemetry is off.

The exporter configuration mirrors the Pydantic AI agent runtime: exporters are
constructed with no explicit endpoint so the SDK reads the full
``OTEL_EXPORTER_OTLP_*`` env surface (endpoint, protocol, TLS, headers,
per-signal overrides). Beyond traces, the service exports Python logs over OTLP
with trace-id/span-id correlation, and can trace outbound HTTP calls (to the
ModelAPI for summarisation/embedding) when ``OTEL_INCLUDE_HTTP_CLIENT`` is set,
keeping the agent->memory->model trace continuous.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("kaos.memory.telemetry")

_LOG_LEVELS = {
    "TRACE": logging.DEBUG,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}


def _log_level_int() -> int:
    """Resolve LOG_LEVEL (defaults to INFO) to a logging constant."""
    return _LOG_LEVELS.get(os.getenv("LOG_LEVEL", "INFO").strip().upper(), logging.INFO)


def _getenv_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean env var (true/1/yes -> True, false/0/no -> False)."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return default


def setup_telemetry(app: Any) -> None:
    """Configure the OTLP tracer provider and instrument ``app`` when enabled.

    Enabled when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set and ``OTEL_SDK_DISABLED``
    is not ``true``. The operator injects both via the MemoryStore telemetry
    block. Missing SDK packages or setup errors are logged and swallowed so
    telemetry never blocks the service from serving.
    """

    if os.getenv("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTLP endpoint set but OpenTelemetry SDK is unavailable; skipping")
        return

    try:
        service_name = os.getenv("OTEL_SERVICE_NAME", "kaos-memory")
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        # No explicit endpoint: the SDK reads OTEL_EXPORTER_OTLP_* env for the
        # endpoint plus protocol, TLS and header configuration, matching pais.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(
            app, excluded_urls=os.getenv("OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", "/healthz,/readyz")
        )
        _setup_log_export(resource)
        _setup_httpx_instrumentation()
        logger.info("OpenTelemetry enabled for memory service -> %s", endpoint)
    except Exception as exc:  # pragma: no cover - defensive, telemetry is best-effort
        logger.warning("Failed to initialise OpenTelemetry: %s", exc)


def _setup_log_export(resource: Any) -> None:
    """Export Python logs over OTLP and correlate them with the active trace.

    Attaches an OTLP log handler to the root logger and enables the logging
    instrumentor so every record carries the current trace-id/span-id, matching
    the agent runtime. Best-effort: missing packages are logged and skipped.
    """

    try:
        from opentelemetry import _logs as otel_logs
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    except ImportError:
        logger.warning("OTLP log export deps unavailable; skipping log correlation")
        return

    class _KaosLoggingHandler(LoggingHandler):
        """Adds logger.name as an explicit attribute for log viewers like SigNoz."""

        def emit(self, record: logging.LogRecord) -> None:
            if not hasattr(record, "logger_name"):
                record.logger_name = record.name
            super().emit(record)

    logger_provider = LoggerProvider(resource=resource)
    # No explicit endpoint: reuse the OTEL_EXPORTER_OTLP_* env surface.
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    otel_logs.set_logger_provider(logger_provider)
    handler = _KaosLoggingHandler(level=_log_level_int(), logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    LoggingInstrumentor().instrument(set_logging_format=False)


def _setup_httpx_instrumentation() -> None:
    """Trace outbound HTTP calls when ``OTEL_INCLUDE_HTTP_CLIENT`` is set.

    Opt-in (like the agent runtime) so the agent->memory->model trace stays
    continuous through the memory service's ModelAPI calls without adding span
    noise by default. Best-effort: a missing instrumentor is logged and skipped.
    """

    if not _getenv_bool("OTEL_INCLUDE_HTTP_CLIENT", False):
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError:
        logger.warning("HTTPX instrumentation requested but package unavailable; skipping")
        return
    HTTPXClientInstrumentor().instrument()
