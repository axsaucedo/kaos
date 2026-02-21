"""
OpenTelemetry setup for KAOS.

Provides SDK initialization using standard OTEL_* environment variables and
lightweight helpers for trace context propagation and delegation metrics.

Span management is handled by:
- Pydantic AI instrumentation (agent run, model call, tool execution spans)
- Standard OTEL context managers (tracer.start_as_current_span) in KAOS code

Key design:
- Process-global SDK initialization via module-level _initialized flag
- Direct OTEL API usage — no custom span stack or context manipulation
- OtelConfig uses pydantic BaseSettings with OTEL-compliant env var names
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict
from opentelemetry import trace, metrics
from opentelemetry import _logs as otel_logs
from opentelemetry.context import Context
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
from opentelemetry.propagate import set_global_textmap, inject, extract
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

logger = logging.getLogger(__name__)


def get_log_level() -> str:
    """Get the configured log level as a string.

    Reads from LOG_LEVEL env var (with AGENT_LOG_LEVEL as fallback for backwards
    compatibility) and returns the normalized level string.
    Defaults to INFO if not set.
    """
    return os.getenv("LOG_LEVEL", os.getenv("AGENT_LOG_LEVEL", "INFO")).upper()


def get_log_level_int() -> int:
    """Get the configured log level as a logging constant.

    Converts the LOG_LEVEL string to logging.DEBUG/INFO/etc.
    Defaults to INFO if not set or invalid.
    """
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
    """Get a boolean value from an environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set (default: False)

    Returns:
        True if the env var is set to 'true', '1', or 'yes' (case-insensitive)
        False if set to 'false', '0', or 'no'
        default if not set or unrecognized value
    """
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
    """Custom LoggingHandler that adds logger name as an explicit attribute.

    The standard LoggingHandler uses logger name for InstrumentationScope but
    excludes it from log record attributes. This subclass adds it back as
    'logger.name' for better visibility in log viewers like SigNoz.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record with logger name as attribute."""
        # Add logger name as attribute before translation
        # This is safe because we're adding to the record, not modifying reserved attrs
        if not hasattr(record, "logger_name"):
            record.logger_name = record.name
        super().emit(record)


# Semantic conventions for KAOS spans
ATTR_AGENT_NAME = "agent.name"
ATTR_SESSION_ID = "session.id"
ATTR_DELEGATION_TARGET = "agent.delegation.target"

# Process-global initialization state
_initialized: bool = False

# Lazily initialized delegation metrics
_delegation_counter: Optional[metrics.Counter] = None
_delegation_duration: Optional[metrics.Histogram] = None


class OtelConfig(BaseSettings):
    """OpenTelemetry configuration from standard OTEL_* environment variables.

    Uses pydantic BaseSettings for automatic env var parsing.
    OTEL_SDK_DISABLED=true disables telemetry (standard OTel env var).
    """

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
        """Check if OTel is enabled (not disabled)."""
        return not self.otel_sdk_disabled


def is_otel_enabled() -> bool:
    """Check if OTel is initialized and enabled.

    Returns True only if init_otel() was successfully called and OTel is active.
    """
    return _initialized


def get_current_trace_context() -> Optional[Dict[str, str]]:
    """Get current trace context (trace_id, span_id) if available.

    Returns:
        Dictionary with trace_id and span_id, or None if no active span.
    """
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
    """Check if OTel should be enabled based on environment variables.

    This checks env vars BEFORE init_otel() is called, useful for deciding
    whether to enable log correlation before the SDK is initialized.

    Returns True if OTEL_SDK_DISABLED is not set to true AND required env vars
    (OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT) are configured.
    """
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() in ("true", "1", "yes")
    if disabled:
        return False

    # Check if required env vars are set
    service_name = os.getenv("OTEL_SERVICE_NAME", "")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    return bool(service_name and endpoint)


def init_otel(service_name: Optional[str] = None) -> bool:
    """Initialize OpenTelemetry with standard OTEL_* env vars.

    Should be called once at process startup. Idempotent - safe to call multiple times.

    Args:
        service_name: Default service name if OTEL_SERVICE_NAME not set (for backward compat)

    Returns:
        True if OTel was initialized, False if disabled or already initialized
    """
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


def _get_service_name() -> str:
    """Get service name from environment variables."""
    return os.getenv("OTEL_SERVICE_NAME", os.getenv("AGENT_NAME", "kaos-service"))


def get_tracer() -> trace.Tracer:
    """Get the KAOS tracer instance.

    Returns the global tracer using the service name. When OTel is not
    initialized, the returned tracer is a no-op tracer.
    """
    service_name = _get_service_name()
    return trace.get_tracer(f"kaos.{service_name}")


def get_delegation_metrics() -> Tuple[Optional[metrics.Counter], Optional[metrics.Histogram]]:
    """Get delegation counter and duration histogram.

    Lazily initializes metrics on first call. Returns (None, None) when
    OTel is not initialized.
    """
    global _delegation_counter, _delegation_duration

    if not _initialized:
        return None, None

    if _delegation_counter is None:
        service_name = _get_service_name()
        meter = metrics.get_meter(f"kaos.{service_name}")
        _delegation_counter = meter.create_counter(
            "kaos.delegations", description="Delegation count", unit="1"
        )
        _delegation_duration = meter.create_histogram(
            "kaos.delegation.duration", description="Delegation duration", unit="ms"
        )

    return _delegation_counter, _delegation_duration


def inject_trace_context(carrier: Dict[str, str]) -> Dict[str, str]:
    """Inject trace context into headers for propagation (e.g., A2A delegation)."""
    inject(carrier)
    return carrier


def extract_trace_context(headers: Any) -> Context:
    """Extract trace context from HTTP headers.

    Args:
        headers: HTTP headers (dict, Starlette Headers, or any mapping)

    Returns:
        Context with extracted trace information (use as parent for new spans)
    """
    carrier = dict(headers) if not isinstance(headers, dict) else headers
    return extract(carrier)
