"""OpenTelemetry setup for KAOS.

Process-global SDK initialization, trace context propagation, and delegation metrics.
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict
from opentelemetry import trace, metrics
from opentelemetry import _logs as otel_logs

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

logger = logging.getLogger(__name__)


def get_log_level() -> str:
    """Return LOG_LEVEL env var (falls back to AGENT_LOG_LEVEL, then INFO)."""
    return os.getenv("LOG_LEVEL", os.getenv("AGENT_LOG_LEVEL", "INFO")).upper()


def get_log_level_int() -> int:
    """Convert LOG_LEVEL string to logging constant (defaults to INFO)."""
    level_str = get_log_level()
    level_map = {
        "TRACE": logging.DEBUG,  # Python doesn't have TRACE
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    return level_map.get(level_str, logging.INFO)


def getenv_bool(name: str, default: bool = False) -> bool:
    """Parse boolean from env var (true/1/yes → True, false/0/no → False)."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return default


class KaosLoggingHandler(LoggingHandler):
    """Adds logger.name as explicit attribute for log viewers like SigNoz."""

    def emit(self, record: logging.LogRecord) -> None:
        # Add logger name as attribute before translation
        # This is safe because we're adding to the record, not modifying reserved attrs
        if not hasattr(record, "logger_name"):
            record.logger_name = record.name
        super().emit(record)


# Semantic conventions for KAOS spans
ATTR_DELEGATION_TARGET = "agent.delegation.target"

# Process-global initialization state
_initialized: bool = False

# Lazily initialized delegation metrics
_delegation_counter: Optional[metrics.Counter] = None
_delegation_duration: Optional[metrics.Histogram] = None


class OtelConfig(BaseSettings):
    """OTel configuration from standard OTEL_* env vars via pydantic BaseSettings."""

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    # Standard OTel env vars - required when telemetry enabled
    otel_service_name: str
    otel_exporter_otlp_endpoint: str

    # Standard OTel env var for disabling SDK (default: false = enabled)
    otel_sdk_disabled: bool = False

    # Resource attributes (optional, we append to existing)
    otel_resource_attributes: str = ""

    @property
    def enabled(self) -> bool:
        return not self.otel_sdk_disabled


def is_otel_enabled() -> bool:
    """Return True only if init_otel() was successfully called."""
    return _initialized


def get_current_trace_context() -> Optional[Dict[str, str]]:
    """Return dict with trace_id and span_id, or None if no active span."""
    if not _initialized:
        return None

    current_span = trace.get_current_span()
    if current_span is None:
        return None

    span_context = current_span.get_span_context()
    if not span_context.is_valid:
        return None

    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def should_enable_otel() -> bool:
    """Check env vars before init_otel() — True if OTEL_SDK_DISABLED!=true and required vars set."""
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() in ("true", "1", "yes")
    if disabled:
        return False

    # Check if required env vars are set
    service_name = os.getenv("OTEL_SERVICE_NAME", "")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    return bool(service_name and endpoint)


def init_otel(service_name: Optional[str] = None) -> bool:
    """Initialize OTel SDK once at process startup. Idempotent."""
    global _initialized

    if _initialized:
        return False

    # Check if OTel is disabled via standard env var
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() in ("true", "1", "yes")
    if disabled:
        logger.debug("OpenTelemetry disabled (OTEL_SDK_DISABLED=true)")
        return False

    # Try to load config from env vars
    try:
        # If service_name provided and OTEL_SERVICE_NAME not set, use it as fallback
        if service_name and not os.getenv("OTEL_SERVICE_NAME"):
            os.environ["OTEL_SERVICE_NAME"] = service_name

        # Require endpoint and service_name when enabled
        if not os.getenv("OTEL_SERVICE_NAME") or not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            logger.debug(
                "OpenTelemetry not configured: "
                "OTEL_SERVICE_NAME and OTEL_EXPORTER_OTLP_ENDPOINT required"
            )
            return False

        config = OtelConfig()  # type: ignore[call-arg]
    except Exception as e:
        logger.warning(f"OpenTelemetry config error: {e}")
        return False

    # Create resource with service name
    resource = Resource.create({SERVICE_NAME: config.otel_service_name})

    # Set up W3C Trace Context propagation (standard)
    set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )

    # Initialize tracing - let SDK use OTEL_EXPORTER_OTLP_* env vars for TLS, headers, etc.
    # By not passing endpoint explicitly, SDK will read from OTEL_EXPORTER_OTLP_ENDPOINT
    tracer_provider = TracerProvider(resource=resource)
    otlp_span_exporter = OTLPSpanExporter()  # Uses OTEL_EXPORTER_OTLP_* env vars
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # Initialize metrics - also uses env vars for endpoint, TLS config, etc.
    otlp_metric_exporter = OTLPMetricExporter()  # Uses OTEL_EXPORTER_OTLP_* env vars
    metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Initialize logs export - exports Python logs to OTLP collector
    otlp_log_exporter = OTLPLogExporter()  # Uses OTEL_EXPORTER_OTLP_* env vars
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))
    otel_logs.set_logger_provider(logger_provider)
    # Attach custom handler to root logger to export all logs at configured level
    # Uses KaosLoggingHandler which adds logger.name as explicit attribute
    log_level = get_log_level_int()
    otel_handler = KaosLoggingHandler(level=log_level, logger_provider=logger_provider)
    logging.getLogger().addHandler(otel_handler)

    logger.info(
        f"OpenTelemetry initialized: {config.otel_exporter_otlp_endpoint} "
        f"(service: {config.otel_service_name})"
    )
    _initialized = True
    return True


# Module-level service name: computed once, used everywhere for tracers and meters
SERVICE_NAME = f"kaos.{os.getenv('OTEL_SERVICE_NAME', os.getenv('AGENT_NAME', 'kaos-service'))}"


def get_delegation_metrics() -> Tuple[Optional[metrics.Counter], Optional[metrics.Histogram]]:
    """Lazily initialize and return (delegation_counter, delegation_duration). (None, None) when disabled."""
    global _delegation_counter, _delegation_duration

    if not _initialized:
        return None, None

    if _delegation_counter is None:
        meter = metrics.get_meter(SERVICE_NAME)
        _delegation_counter = meter.create_counter(
            "kaos.delegations", description="Delegation count", unit="1"
        )
        _delegation_duration = meter.create_histogram(
            "kaos.delegation.duration", description="Delegation duration", unit="ms"
        )

    return _delegation_counter, _delegation_duration
