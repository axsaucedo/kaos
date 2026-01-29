"""
OpenTelemetry Manager for KAOS.

Provides a simplified interface for OpenTelemetry instrumentation using standard
OTEL_* environment variables. Uses OTEL_SDK_DISABLED (standard OTel env var) to
control whether telemetry is enabled.

Key design:
- Process-global SDK initialization via module-level _initialized flag
- Inline span management via span_begin/span_success/span_failure (no context managers)
- Async-safe span stack via contextvars for nesting support
- OtelConfig uses pydantic BaseSettings with OTEL-compliant env var names
"""

import logging
import os
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from opentelemetry import trace, metrics, context as otel_context
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
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.context import Context

logger = logging.getLogger(__name__)


def _get_log_level() -> int:
    """Get the configured log level as a logging constant.

    Reads from LOG_LEVEL env var and converts to logging.DEBUG/INFO/etc.
    Defaults to INFO if not set or invalid.
    """
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level_map = {
        "TRACE": logging.DEBUG,  # Python doesn't have TRACE
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    return level_map.get(level_str, logging.INFO)


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
ATTR_MODEL_NAME = "gen_ai.request.model"
ATTR_TOOL_NAME = "tool.name"
ATTR_DELEGATION_TARGET = "agent.delegation.target"

# Process-global initialization state
_initialized: bool = False


@dataclass
class SpanState:
    """State for an active span on the stack."""

    span: Span
    token: Token[Context]  # Context token for detaching
    start_time: float
    metric_kind: Optional[str] = None  # "request", "model", "tool", "delegation"
    metric_attrs: Dict[str, Any] = field(default_factory=dict)
    ended: bool = False


# Async-safe span stack per context (supports nesting)
# default=None to avoid shared mutable list across async contexts
_span_stack: ContextVar[Optional[List[SpanState]]] = ContextVar("kaos_span_stack", default=None)


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
    log_level = _get_log_level()
    otel_handler = KaosLoggingHandler(level=log_level, logger_provider=logger_provider)
    logging.getLogger().addHandler(otel_handler)

    logger.info(
        f"OpenTelemetry initialized: {config.otel_exporter_otlp_endpoint} "
        f"(service: {config.otel_service_name})"
    )
    _initialized = True
    return True


class KaosOtelManager:
    """Lightweight helper for creating spans and recording metrics.

    Uses inline span management via span_begin/span_success/span_failure instead
    of context managers. Timing is handled internally via contextvars.

    Example:
        otel = KaosOtelManager("my-agent")
        otel.span_begin("process_request", attrs={"session.id": "abc123"})
        try:
            # do work
            pass
        except Exception as e:
            otel.span_failure(e)
            raise
        else:
            otel.span_success()
    """

    def __init__(self, service_name: str):
        """Initialize manager with service context.

        Args:
            service_name: Name of the service (e.g., agent name)
        """
        self.service_name = service_name
        self._tracer = trace.get_tracer(f"kaos.{service_name}")
        self._meter = metrics.get_meter(f"kaos.{service_name}")

        # Lazily initialized metrics
        self._request_counter: Optional[metrics.Counter] = None
        self._request_duration: Optional[metrics.Histogram] = None
        self._model_counter: Optional[metrics.Counter] = None
        self._model_duration: Optional[metrics.Histogram] = None
        self._tool_counter: Optional[metrics.Counter] = None
        self._tool_duration: Optional[metrics.Histogram] = None
        self._delegation_counter: Optional[metrics.Counter] = None
        self._delegation_duration: Optional[metrics.Histogram] = None

    def _ensure_metrics(self) -> None:
        """Lazily initialize metric instruments."""
        if self._request_counter is not None:
            return

        self._request_counter = self._meter.create_counter(
            "kaos.requests", description="Request count", unit="1"
        )
        self._request_duration = self._meter.create_histogram(
            "kaos.request.duration", description="Request duration", unit="ms"
        )
        self._model_counter = self._meter.create_counter(
            "kaos.model.calls", description="Model API call count", unit="1"
        )
        self._model_duration = self._meter.create_histogram(
            "kaos.model.duration", description="Model API call duration", unit="ms"
        )
        self._tool_counter = self._meter.create_counter(
            "kaos.tool.calls", description="Tool call count", unit="1"
        )
        self._tool_duration = self._meter.create_histogram(
            "kaos.tool.duration", description="Tool call duration", unit="ms"
        )
        self._delegation_counter = self._meter.create_counter(
            "kaos.delegations", description="Delegation count", unit="1"
        )
        self._delegation_duration = self._meter.create_histogram(
            "kaos.delegation.duration", description="Delegation duration", unit="ms"
        )

    def _get_stack(self) -> List[SpanState]:
        """Get or create the span stack for current async context.

        Allocates a new list per-context to avoid sharing mutable state.
        """
        stack = _span_stack.get()
        if stack is None:
            stack = []
            _span_stack.set(stack)
        return stack

    def span_begin(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        attrs: Optional[Dict[str, Any]] = None,
        metric_kind: Optional[str] = None,
        metric_attrs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Begin a span. Must be paired with span_success() or span_failure().

        Args:
            name: Span name
            kind: Span kind (INTERNAL, CLIENT, SERVER)
            attrs: Span attributes
            metric_kind: Type of metric to record ("request", "model", "tool", "delegation")
            metric_attrs: Additional attributes for metric recording
        """
        if not _initialized:
            return

        # Build attributes
        span_attrs = {ATTR_AGENT_NAME: self.service_name}
        if attrs:
            span_attrs.update({k: v for k, v in attrs.items() if v is not None})

        # Start span and make it current
        span = self._tracer.start_span(name, kind=kind, attributes=span_attrs)
        token = otel_context.attach(trace.set_span_in_context(span))

        # Push state onto stack
        state = SpanState(
            span=span,
            token=token,
            start_time=time.perf_counter(),
            metric_kind=metric_kind,
            metric_attrs=metric_attrs or {},
        )
        stack = self._get_stack()
        stack.append(state)

    def span_success(self) -> None:
        """End the current span with OK status. No-op if already ended or OTel disabled."""
        if not _initialized:
            return

        stack = self._get_stack()
        if not stack:
            return

        state = stack[-1]
        if state.ended:
            return

        # Mark ended and calculate duration
        state.ended = True
        duration_ms = (time.perf_counter() - state.start_time) * 1000

        # Set status and end span
        state.span.set_status(Status(StatusCode.OK))
        state.span.end()

        # Detach context
        otel_context.detach(state.token)

        # Record metrics
        self._record_metric(state.metric_kind, state.metric_attrs, duration_ms, success=True)

        # Pop from stack
        stack.pop()

    def span_failure(self, exc: Exception) -> None:
        """End the current span with ERROR status. Records the exception."""
        if not _initialized:
            return

        stack = self._get_stack()
        if not stack:
            return

        state = stack[-1]
        if state.ended:
            return

        # Mark ended and calculate duration
        state.ended = True
        duration_ms = (time.perf_counter() - state.start_time) * 1000

        # Set status, record exception, and end span
        state.span.set_status(Status(StatusCode.ERROR, str(exc)))
        state.span.record_exception(exc)
        state.span.end()

        # Detach context
        otel_context.detach(state.token)

        # Record metrics
        self._record_metric(state.metric_kind, state.metric_attrs, duration_ms, success=False)

        # Pop from stack
        stack.pop()

    def _record_metric(
        self,
        metric_kind: Optional[str],
        metric_attrs: Dict[str, Any],
        duration_ms: float,
        success: bool,
    ) -> None:
        """Record metrics based on metric_kind."""
        if not metric_kind:
            return

        self._ensure_metrics()

        if metric_kind == "request":
            labels = {"agent.name": self.service_name, "success": str(success).lower()}
            if self._request_counter:
                self._request_counter.add(1, labels)
            if self._request_duration:
                self._request_duration.record(duration_ms, labels)

        elif metric_kind == "model":
            model = metric_attrs.get("model", "unknown")
            labels = {
                "agent.name": self.service_name,
                "model": model,
                "success": str(success).lower(),
            }
            if self._model_counter:
                self._model_counter.add(1, labels)
            if self._model_duration:
                self._model_duration.record(duration_ms, labels)

        elif metric_kind == "tool":
            tool = metric_attrs.get("tool", "unknown")
            labels = {
                "agent.name": self.service_name,
                "tool": tool,
                "success": str(success).lower(),
            }
            if self._tool_counter:
                self._tool_counter.add(1, labels)
            if self._tool_duration:
                self._tool_duration.record(duration_ms, labels)

        elif metric_kind == "delegation":
            target = metric_attrs.get("target", "unknown")
            labels = {
                "agent.name": self.service_name,
                "target": target,
                "success": str(success).lower(),
            }
            if self._delegation_counter:
                self._delegation_counter.add(1, labels)
            if self._delegation_duration:
                self._delegation_duration.record(duration_ms, labels)

    @staticmethod
    def inject_context(carrier: Dict[str, str]) -> Dict[str, str]:
        """Inject trace context into headers for propagation."""
        inject(carrier)
        return carrier

    @staticmethod
    def extract_context(carrier: Dict[str, str]) -> Context:
        """Extract trace context from headers."""
        return extract(carrier)
