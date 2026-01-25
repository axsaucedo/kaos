"""
Tests for OpenTelemetry instrumentation.
"""

import pytest
import os
import time
from unittest.mock import patch


class TestIsOtelEnabled:
    """Tests for is_otel_enabled utility."""

    def test_enabled_by_default(self):
        """Test that telemetry is enabled by default (OTEL_SDK_DISABLED not set)."""
        with patch.dict(os.environ, {}, clear=True):
            from telemetry.manager import is_otel_enabled

            assert is_otel_enabled() is True

    def test_disabled_with_true(self):
        """Test disabling with OTEL_SDK_DISABLED=true."""
        with patch.dict(os.environ, {"OTEL_SDK_DISABLED": "true"}, clear=True):
            from telemetry.manager import is_otel_enabled

            assert is_otel_enabled() is False

    def test_disabled_with_one(self):
        """Test disabling with OTEL_SDK_DISABLED=1."""
        with patch.dict(os.environ, {"OTEL_SDK_DISABLED": "1"}, clear=True):
            from telemetry.manager import is_otel_enabled

            assert is_otel_enabled() is False

    def test_enabled_with_false(self):
        """Test explicitly enabled with OTEL_SDK_DISABLED=false."""
        with patch.dict(os.environ, {"OTEL_SDK_DISABLED": "false"}, clear=True):
            from telemetry.manager import is_otel_enabled

            assert is_otel_enabled() is True


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

    def test_span_context_manager(self):
        """Test span context manager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        with manager.span("test-operation") as span:
            assert span is not None

    def test_record_request(self):
        """Test record_request doesn't raise errors."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.record_request(100.0, success=True)

    def test_record_request_with_failure(self):
        """Test record_request with success=False."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.record_request(100.0, success=False)

    def test_record_model_call(self):
        """Test record_model_call doesn't raise errors."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.record_model_call("gpt-4", 500.0, success=True)

    def test_record_tool_call(self):
        """Test record_tool_call doesn't raise errors."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.record_tool_call("calculator", 50.0, success=True)

    def test_record_delegation(self):
        """Test record_delegation doesn't raise errors."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        manager.record_delegation("worker-1", 200.0, success=True)

    def test_model_span_context_manager(self):
        """Test model_span context manager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        with manager.model_span("gpt-4") as span:
            assert span is not None

    def test_tool_span_context_manager(self):
        """Test tool_span context manager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        with manager.tool_span("calculator") as span:
            assert span is not None

    def test_delegation_span_context_manager(self):
        """Test delegation_span context manager."""
        from telemetry.manager import KaosOtelManager

        manager = KaosOtelManager("test-agent")
        with manager.delegation_span("worker-1") as span:
            assert span is not None


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


class TestTimedContextManager:
    """Tests for timed context manager."""

    def test_timed_operation(self):
        """Test timed context manager tracks duration."""
        from telemetry.manager import timed

        with timed() as result:
            time.sleep(0.01)

        assert "duration_ms" in result
        assert result["duration_ms"] >= 10  # At least 10ms


class TestMCPServerTelemetrySimplified:
    """Tests for MCPServer simplified telemetry settings."""

    def test_otel_enabled_by_default(self):
        """Test that OTel is enabled by default (OTEL_SDK_DISABLED not set)."""
        with patch.dict(os.environ, {}, clear=True):
            from mcptools.server import MCPServer, MCPServerSettings

            settings = MCPServerSettings()
            server = MCPServer(settings)
            assert server._otel_enabled is True

    def test_otel_disabled_from_env(self):
        """Test that OTel can be disabled via OTEL_SDK_DISABLED env var."""
        with patch.dict(os.environ, {"OTEL_SDK_DISABLED": "true"}, clear=True):
            from mcptools.server import MCPServer, MCPServerSettings

            settings = MCPServerSettings()
            server = MCPServer(settings)
            assert server._otel_enabled is False
