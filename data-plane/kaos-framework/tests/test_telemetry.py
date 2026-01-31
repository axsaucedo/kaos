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
        import telemetry.manager as tm

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
            from telemetry.manager import should_enable_otel

            assert should_enable_otel() is False

    def test_returns_false_without_service_name(self):
        """Test should_enable_otel returns False without OTEL_SERVICE_NAME."""
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"},
            clear=True,
        ):
            from telemetry.manager import should_enable_otel

            assert should_enable_otel() is False

    def test_returns_false_without_endpoint(self):
        """Test should_enable_otel returns False without OTEL_EXPORTER_OTLP_ENDPOINT."""
        with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "test-agent"}, clear=True):
            from telemetry.manager import should_enable_otel

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
            from telemetry.manager import should_enable_otel

            assert should_enable_otel() is True


class TestOtelConfig:
    """Tests for OtelConfig pydantic BaseSettings."""

    def test_config_requires_service_name_and_endpoint(self):
        """Test that config requires OTEL_SERVICE_NAME and OTEL_EXPORTER_OTLP_ENDPOINT."""
        with patch.dict(os.environ, {}, clear=True):
            from telemetry.manager import OtelConfig
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
            from telemetry.manager import OtelConfig

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
            from telemetry.manager import OtelConfig

            config = OtelConfig()  # type: ignore[call-arg]
            assert config.enabled is False


class TestKaosOtelManager:
    """Tests for KaosOtelManager class."""

    def setup_method(self):
        """Reset singleton before each test."""
        from telemetry.manager import KaosOtelManager

        KaosOtelManager._reset_for_testing()

    def teardown_method(self):
        """Reset singleton after each test."""
        from telemetry.manager import KaosOtelManager

        KaosOtelManager._reset_for_testing()

    def test_manager_creation(self):
        """Test creating a KaosOtelManager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        assert manager.service_name == "test-agent"

    def test_tracer_available(self):
        """Test getting a tracer from manager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        assert manager._tracer is not None

    def test_meter_available(self):
        """Test getting a meter from manager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        assert manager._meter is not None

    def test_span_begin_success_pattern(self):
        """Test span_begin/span_success pattern (no-op when not initialized)."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.span_begin("test-operation")
        try:
            pass  # do work
        except Exception as e:
            manager.span_failure(e)
            raise
        else:
            manager.span_success()

    def test_span_begin_failure_pattern(self):
        """Test span_begin/span_failure pattern."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.span_begin("test-operation")
        try:
            raise ValueError("test error")
        except ValueError as e:
            manager.span_failure(e)
        else:
            manager.span_success()

    def test_nested_spans(self):
        """Test nested span_begin calls."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.span_begin("outer")
        try:
            manager.span_begin("inner")
            try:
                pass
            except Exception as e:
                manager.span_failure(e)
                raise
            else:
                manager.span_success()
        except Exception as e:
            manager.span_failure(e)
            raise
        else:
            manager.span_success()

    def test_span_with_metric_kind(self):
        """Test span_begin with metric_kind parameter."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.span_begin(
            "model.inference",
            metric_kind="model",
            metric_attrs={"model": "gpt-4"},
        )
        try:
            pass
        except Exception as e:
            manager.span_failure(e)
            raise
        else:
            manager.span_success()


class TestContextPropagation:
    """Tests for trace context propagation."""

    def test_inject_context(self):
        """Test context injection into headers."""
        from telemetry.manager import KaosOtelManager

        carrier: dict = {}
        result = KaosOtelManager.inject_context(carrier)
        assert isinstance(result, dict)

    def test_extract_context(self):
        """Test context extraction from headers."""
        from telemetry.manager import KaosOtelManager

        carrier: dict = {}
        context = KaosOtelManager.extract_context(carrier)
        assert context is not None
