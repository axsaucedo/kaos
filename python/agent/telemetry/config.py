"""
OpenTelemetry configuration and initialization for KAOS agents.

Configures tracing, metrics, and log correlation based on environment variables.
Supports OTLP export to any OpenTelemetry-compatible backend.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

logger = logging.getLogger(__name__)


@dataclass
class TelemetryConfig:
    """Configuration for OpenTelemetry instrumentation.

    Environment variables:
        OTEL_ENABLED: Enable/disable telemetry (default: false)
        OTEL_SERVICE_NAME: Service name for traces (default: agent name)
        OTEL_SERVICE_VERSION: Service version (default: 0.0.1)
        OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (default: http://localhost:4317)
        OTEL_EXPORTER_OTLP_INSECURE: Use insecure connection (default: true)
        OTEL_TRACES_ENABLED: Enable tracing (default: true when OTEL_ENABLED)
        OTEL_METRICS_ENABLED: Enable metrics (default: true when OTEL_ENABLED)
        OTEL_LOG_CORRELATION: Enable log correlation (default: true when OTEL_ENABLED)
        OTEL_CONSOLE_EXPORT: Export to console for debugging (default: false)
    """

    enabled: bool = False
    service_name: str = "kaos-agent"
    service_version: str = "0.0.1"
    otlp_endpoint: str = "http://localhost:4317"
    otlp_insecure: bool = True
    traces_enabled: bool = True
    metrics_enabled: bool = True
    log_correlation: bool = True
    console_export: bool = False
    extra_attributes: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, agent_name: Optional[str] = None) -> "TelemetryConfig":
        """Create configuration from environment variables."""
        enabled = os.getenv("OTEL_ENABLED", "false").lower() in ("true", "1", "yes")

        return cls(
            enabled=enabled,
            service_name=os.getenv("OTEL_SERVICE_NAME", agent_name or "kaos-agent"),
            service_version=os.getenv("OTEL_SERVICE_VERSION", "0.0.1"),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            otlp_insecure=os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower()
            in ("true", "1", "yes"),
            traces_enabled=os.getenv("OTEL_TRACES_ENABLED", "true").lower() in ("true", "1", "yes"),
            metrics_enabled=os.getenv("OTEL_METRICS_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            log_correlation=os.getenv("OTEL_LOG_CORRELATION", "true").lower()
            in ("true", "1", "yes"),
            console_export=os.getenv("OTEL_CONSOLE_EXPORT", "false").lower()
            in ("true", "1", "yes"),
        )


# Global state for initialized providers
_tracer_provider: Optional[TracerProvider] = None
_meter_provider: Optional[MeterProvider] = None
_initialized: bool = False


def init_telemetry(config: TelemetryConfig) -> bool:
    """Initialize OpenTelemetry with the given configuration.

    Returns True if telemetry was initialized, False if disabled or already initialized.
    """
    global _tracer_provider, _meter_provider, _initialized

    if _initialized:
        logger.debug("Telemetry already initialized")
        return False

    if not config.enabled:
        logger.info("OpenTelemetry disabled (OTEL_ENABLED=false)")
        _initialized = True
        return False

    # Create resource with service information
    resource = Resource.create(
        {
            SERVICE_NAME: config.service_name,
            SERVICE_VERSION: config.service_version,
            "deployment.environment": os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
            **config.extra_attributes,
        }
    )

    # Set up context propagation (W3C Trace Context + Baggage)
    set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )

    # Initialize tracing
    if config.traces_enabled:
        _tracer_provider = TracerProvider(resource=resource)

        if config.console_export:
            _tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        if config.otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(
                endpoint=config.otlp_endpoint,
                insecure=config.otlp_insecure,
            )
            _tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        trace.set_tracer_provider(_tracer_provider)
        logger.info(f"OpenTelemetry tracing initialized: {config.otlp_endpoint}")

    # Initialize metrics
    if config.metrics_enabled:
        readers = []

        if config.console_export:
            readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))

        if config.otlp_endpoint:
            otlp_metric_exporter = OTLPMetricExporter(
                endpoint=config.otlp_endpoint,
                insecure=config.otlp_insecure,
            )
            readers.append(PeriodicExportingMetricReader(otlp_metric_exporter))

        if readers:
            _meter_provider = MeterProvider(resource=resource, metric_readers=readers)
            metrics.set_meter_provider(_meter_provider)
            logger.info(f"OpenTelemetry metrics initialized: {config.otlp_endpoint}")

    _initialized = True
    return True


def shutdown_telemetry() -> None:
    """Shutdown OpenTelemetry providers gracefully."""
    global _tracer_provider, _meter_provider, _initialized

    if _tracer_provider:
        _tracer_provider.shutdown()
        _tracer_provider = None

    if _meter_provider:
        _meter_provider.shutdown()
        _meter_provider = None

    _initialized = False
    logger.info("OpenTelemetry shutdown complete")


def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled and initialized."""
    return _initialized and (_tracer_provider is not None or _meter_provider is not None)
