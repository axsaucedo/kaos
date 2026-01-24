"""
Tests for OpenTelemetry instrumentation.
"""

import pytest
import os
from unittest.mock import patch, MagicMock


class TestTelemetryConfig:
    """Tests for TelemetryConfig."""

    def test_config_from_env_disabled_by_default(self):
        """Test that telemetry is disabled by default."""
        from agent.telemetry.config import TelemetryConfig

        config = TelemetryConfig.from_env()
        assert config.enabled is False
        assert config.service_name == "kaos-agent"

    def test_config_from_env_with_custom_values(self):
        """Test configuration from environment variables."""
        from agent.telemetry.config import TelemetryConfig

        with patch.dict(
            os.environ,
            {
                "OTEL_ENABLED": "true",
                "OTEL_SERVICE_NAME": "test-agent",
                "OTEL_SERVICE_VERSION": "1.0.0",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            },
        ):
            config = TelemetryConfig.from_env()
            assert config.enabled is True
            assert config.service_name == "test-agent"
            assert config.service_version == "1.0.0"
            assert config.otlp_endpoint == "http://collector:4317"

    def test_config_from_env_with_agent_name(self):
        """Test that agent_name is used as default service name."""
        from agent.telemetry.config import TelemetryConfig

        config = TelemetryConfig.from_env(agent_name="my-agent")
        assert config.service_name == "my-agent"


class TestTracingUtilities:
    """Tests for tracing utilities."""

    def test_get_tracer(self):
        """Test getting a tracer."""
        from agent.telemetry.tracing import get_tracer

        tracer = get_tracer()
        assert tracer is not None

    def test_inject_extract_context(self):
        """Test context injection and extraction."""
        from agent.telemetry.tracing import inject_context, extract_context

        carrier: dict = {}
        inject_context(carrier)
        # Context may or may not have traceparent depending on active span
        context = extract_context(carrier)
        assert context is not None


class TestMetrics:
    """Tests for metrics recording."""

    def test_record_request_no_error(self):
        """Test that record_request doesn't raise errors."""
        from agent.telemetry.metrics import record_request

        # Should not raise
        record_request("test-agent", 100.0, success=True, stream=False)

    def test_record_model_call_no_error(self):
        """Test that record_model_call doesn't raise errors."""
        from agent.telemetry.metrics import record_model_call

        # Should not raise
        record_model_call("test-agent", "gpt-4", 500.0, success=True)

    def test_record_tool_call_no_error(self):
        """Test that record_tool_call doesn't raise errors."""
        from agent.telemetry.metrics import record_tool_call

        # Should not raise
        record_tool_call("test-agent", "calculator", 50.0, success=True)

    def test_record_delegation_no_error(self):
        """Test that record_delegation doesn't raise errors."""
        from agent.telemetry.metrics import record_delegation

        # Should not raise
        record_delegation("test-agent", "worker-1", 200.0, success=True)

    def test_record_agentic_step_no_error(self):
        """Test that record_agentic_step doesn't raise errors."""
        from agent.telemetry.metrics import record_agentic_step

        # Should not raise
        record_agentic_step("test-agent", 1, "model")

    def test_timed_operation(self):
        """Test timed_operation context manager."""
        import time
        from agent.telemetry.metrics import timed_operation

        with timed_operation("test") as result:
            time.sleep(0.01)

        assert "duration_ms" in result
        assert result["duration_ms"] >= 10  # At least 10ms


class TestAgentServerTelemetrySettings:
    """Tests for AgentServer telemetry settings."""

    def test_default_otel_settings(self):
        """Test that OTel is disabled by default in AgentServerSettings."""
        with patch.dict(
            os.environ,
            {
                "AGENT_NAME": "test",
                "MODEL_API_URL": "http://localhost:8000",
                "MODEL_NAME": "test-model",
            },
            clear=True,
        ):
            from agent.server import AgentServerSettings

            settings = AgentServerSettings()  # type: ignore[call-arg]
            assert settings.otel_enabled is False
            assert settings.otel_traces_enabled is True
            assert settings.otel_metrics_enabled is True

    def test_otel_settings_from_env(self):
        """Test OTel settings from environment variables."""
        with patch.dict(
            os.environ,
            {
                "AGENT_NAME": "test",
                "MODEL_API_URL": "http://localhost:8000",
                "MODEL_NAME": "test-model",
                "OTEL_ENABLED": "true",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            },
            clear=True,
        ):
            from agent.server import AgentServerSettings

            settings = AgentServerSettings()  # type: ignore[call-arg]
            assert settings.otel_enabled is True
            assert settings.otel_exporter_otlp_endpoint == "http://collector:4317"


class TestMCPServerTelemetrySettings:
    """Tests for MCPServer telemetry settings."""

    def test_default_otel_settings(self):
        """Test that OTel is disabled by default in MCPServerSettings."""
        from mcptools.server import MCPServerSettings

        settings = MCPServerSettings()
        assert settings.otel_enabled is False
        assert settings.otel_traces_enabled is True

    def test_otel_settings_from_env(self):
        """Test OTel settings from environment variables."""
        with patch.dict(
            os.environ,
            {
                "OTEL_ENABLED": "true",
                "OTEL_SERVICE_NAME": "my-mcp-server",
            },
            clear=True,
        ):
            from mcptools.server import MCPServerSettings

            settings = MCPServerSettings()
            assert settings.otel_enabled is True
            assert settings.otel_service_name == "my-mcp-server"
