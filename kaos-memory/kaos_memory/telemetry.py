"""OpenTelemetry bootstrap for the memory service.

The service emits spans via ``trace.get_tracer("kaos.memory")`` regardless of
configuration; those spans are dropped by the default no-op provider unless a
real ``TracerProvider`` with an OTLP exporter is installed. ``setup_telemetry``
installs one — and instruments the FastAPI app — only when an OTLP endpoint is
configured and the SDK is not explicitly disabled, so the service stays cheap
when telemetry is off.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("kaos.memory.telemetry")


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
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(
            app, excluded_urls=os.getenv("OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", "/healthz,/readyz")
        )
        logger.info("OpenTelemetry enabled for memory service -> %s", endpoint)
    except Exception as exc:  # pragma: no cover - defensive, telemetry is best-effort
        logger.warning("Failed to initialise OpenTelemetry: %s", exc)
