"""
OpenTelemetry instrumentation for KAOS agents.

Provides tracing, metrics, and log correlation for:
- Agent processing (agentic loop, tool calls, delegations)
- Model API calls (LLM inference)
- MCP tool execution
- A2A agent communication
"""

from agent.telemetry.config import TelemetryConfig, init_telemetry
from agent.telemetry.tracing import (
    get_tracer,
    get_current_span,
    inject_context,
    extract_context,
    span_attributes,
)
from agent.telemetry.metrics import (
    get_meter,
    record_request,
    record_model_call,
    record_tool_call,
    record_delegation,
)

__all__ = [
    # Configuration
    "TelemetryConfig",
    "init_telemetry",
    # Tracing
    "get_tracer",
    "get_current_span",
    "inject_context",
    "extract_context",
    "span_attributes",
    # Metrics
    "get_meter",
    "record_request",
    "record_model_call",
    "record_tool_call",
    "record_delegation",
]
