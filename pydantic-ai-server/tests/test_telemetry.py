"""
Tests for OpenTelemetry instrumentation.
"""

import os
import pytest
from unittest.mock import patch


class TestIsOtelEnabled:
    """Tests for is_otel_enabled utility."""

    def test_returns_false_before_init(self):
        """Test that is_otel_enabled returns False before initialization."""
        # Import fresh module - is_otel_enabled checks _initialized flag, not env var
        import pais.telemetry as tm

        # Reset module state for testing
        original = tm._initialized
        tm._initialized = False
        try:
            assert tm.is_otel_enabled() is False
        finally:
            tm._initialized = original


class TestShouldEnableOtel:
    """Tests for should_enable_otel utility."""

    def test_returns_false_when_disabled(self):
        """Test should_enable_otel returns False when OTEL_SDK_DISABLED=true."""
        with patch.dict(
            os.environ,
            {
                "OTEL_SDK_DISABLED": "true",
                "OTEL_SERVICE_NAME": "test-agent",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            },
            clear=True,
        ):
            from pais.telemetry import should_enable_otel

            assert should_enable_otel() is False

    def test_returns_false_without_service_name(self):
        """Test should_enable_otel returns False without OTEL_SERVICE_NAME."""
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"},
            clear=True,
        ):
            from pais.telemetry import should_enable_otel

            assert should_enable_otel() is False

    def test_returns_false_without_endpoint(self):
        """Test should_enable_otel returns False without OTEL_EXPORTER_OTLP_ENDPOINT."""
        with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "test-agent"}, clear=True):
            from pais.telemetry import should_enable_otel

            assert should_enable_otel() is False

    def test_returns_true_with_required_vars(self):
        """Test should_enable_otel returns True with required env vars."""
        with patch.dict(
            os.environ,
            {
                "OTEL_SERVICE_NAME": "test-agent",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            },
            clear=True,
        ):
            from pais.telemetry import should_enable_otel

            assert should_enable_otel() is True


class TestOtelConfig:
    """Tests for OtelConfig pydantic BaseSettings."""

    def test_config_requires_service_name_and_endpoint(self):
        """Test that config requires OTEL_SERVICE_NAME and OTEL_EXPORTER_OTLP_ENDPOINT."""
        with patch.dict(os.environ, {}, clear=True):
            from pais.telemetry import OtelConfig
            from pydantic import ValidationError

            with pytest.raises(ValidationError):
                OtelConfig()  # type: ignore[call-arg]

    def test_config_with_required_values(self):
        """Test configuration from environment variables."""
        with patch.dict(
            os.environ,
            {
                "OTEL_SERVICE_NAME": "test-agent",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            },
            clear=True,
        ):
            from pais.telemetry import OtelConfig

            config = OtelConfig()  # type: ignore[call-arg]
            assert config.otel_service_name == "test-agent"
            assert config.otel_exporter_otlp_endpoint == "http://collector:4317"
            assert config.enabled is True

    def test_config_disabled_with_sdk_disabled(self):
        """Test config.enabled is False when OTEL_SDK_DISABLED=true."""
        with patch.dict(
            os.environ,
            {
                "OTEL_SDK_DISABLED": "true",
                "OTEL_SERVICE_NAME": "test-agent",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            },
            clear=True,
        ):
            from pais.telemetry import OtelConfig

            config = OtelConfig()  # type: ignore[call-arg]
            assert config.enabled is False


class TestTracerAndMetrics:
    """Tests for SERVICE_NAME and get_delegation_metrics helpers."""

    def test_service_name(self):
        """Test SERVICE_NAME is set."""
        from pais.telemetry import SERVICE_NAME

        assert SERVICE_NAME is not None
        assert SERVICE_NAME.startswith("kaos.")

    def test_get_delegation_metrics_when_not_initialized(self):
        """Test get_delegation_metrics returns (None, None) when not initialized."""
        import pais.telemetry as tm

        original = tm._initialized
        tm._initialized = False
        try:
            counter, histogram = tm.get_delegation_metrics()
            assert counter is None
            assert histogram is None
        finally:
            tm._initialized = original

    def test_tracer_start_as_current_span(self):
        """Test using tracer context manager for spans."""
        from opentelemetry import trace
        from pais.telemetry import SERVICE_NAME

        tracer = trace.get_tracer(SERVICE_NAME)
        with tracer.start_as_current_span("test-span") as span:
            assert span is not None


class TestContextPropagation:
    """Tests for trace context propagation via opentelemetry."""

    def test_inject_context(self):
        """Test context injection into headers."""
        from opentelemetry.propagate import inject

        carrier: dict = {}
        inject(carrier)
        assert isinstance(carrier, dict)

    def test_extract_context(self):
        """Test context extraction from headers."""
        from opentelemetry.propagate import extract

        carrier: dict = {}
        context = extract(carrier)
        assert context is not None
