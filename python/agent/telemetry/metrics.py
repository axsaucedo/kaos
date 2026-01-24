"""
Metrics utilities for KAOS agents.

Provides counters, histograms, and gauges for:
- Request processing
- Model API calls
- Tool execution
- A2A delegation
- Memory/session management
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, UpDownCounter

logger = logging.getLogger(__name__)

# Meter name for KAOS components
METER_NAME = "kaos.agent"

# Cached meter and instruments
_meter: Optional[metrics.Meter] = None
_request_counter: Optional[Counter] = None
_request_duration: Optional[Histogram] = None
_model_call_counter: Optional[Counter] = None
_model_call_duration: Optional[Histogram] = None
_tool_call_counter: Optional[Counter] = None
_tool_call_duration: Optional[Histogram] = None
_delegation_counter: Optional[Counter] = None
_delegation_duration: Optional[Histogram] = None
_active_sessions: Optional[UpDownCounter] = None
_agentic_steps: Optional[Counter] = None


def get_meter(name: str = METER_NAME) -> metrics.Meter:
    """Get a meter for creating instruments."""
    return metrics.get_meter(name)


def _ensure_instruments() -> None:
    """Lazily initialize metric instruments."""
    global _meter, _request_counter, _request_duration
    global _model_call_counter, _model_call_duration
    global _tool_call_counter, _tool_call_duration
    global _delegation_counter, _delegation_duration
    global _active_sessions, _agentic_steps

    if _meter is not None:
        return

    _meter = get_meter()

    # Request metrics
    _request_counter = _meter.create_counter(
        name="kaos.agent.requests",
        description="Number of agent requests processed",
        unit="1",
    )
    _request_duration = _meter.create_histogram(
        name="kaos.agent.request.duration",
        description="Duration of agent request processing",
        unit="ms",
    )

    # Model API metrics
    _model_call_counter = _meter.create_counter(
        name="kaos.agent.model.calls",
        description="Number of model API calls",
        unit="1",
    )
    _model_call_duration = _meter.create_histogram(
        name="kaos.agent.model.duration",
        description="Duration of model API calls",
        unit="ms",
    )

    # Tool execution metrics
    _tool_call_counter = _meter.create_counter(
        name="kaos.agent.tool.calls",
        description="Number of tool calls",
        unit="1",
    )
    _tool_call_duration = _meter.create_histogram(
        name="kaos.agent.tool.duration",
        description="Duration of tool calls",
        unit="ms",
    )

    # Delegation metrics
    _delegation_counter = _meter.create_counter(
        name="kaos.agent.delegations",
        description="Number of A2A delegations",
        unit="1",
    )
    _delegation_duration = _meter.create_histogram(
        name="kaos.agent.delegation.duration",
        description="Duration of A2A delegations",
        unit="ms",
    )

    # Session metrics
    _active_sessions = _meter.create_up_down_counter(
        name="kaos.agent.sessions.active",
        description="Number of active sessions",
        unit="1",
    )

    # Agentic loop metrics
    _agentic_steps = _meter.create_counter(
        name="kaos.agent.agentic.steps",
        description="Number of agentic loop steps",
        unit="1",
    )


def record_request(
    agent_name: str,
    duration_ms: float,
    success: bool = True,
    stream: bool = False,
    **attributes: Any,
) -> None:
    """Record a request metric."""
    _ensure_instruments()
    if _request_counter and _request_duration:
        labels = {
            "agent.name": agent_name,
            "success": str(success).lower(),
            "stream": str(stream).lower(),
            **{k: str(v) for k, v in attributes.items() if v is not None},
        }
        _request_counter.add(1, labels)
        _request_duration.record(duration_ms, labels)


def record_model_call(
    agent_name: str,
    model_name: str,
    duration_ms: float,
    success: bool = True,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    **attributes: Any,
) -> None:
    """Record a model API call metric."""
    _ensure_instruments()
    if _model_call_counter and _model_call_duration:
        labels = {
            "agent.name": agent_name,
            "model.name": model_name,
            "success": str(success).lower(),
            **{k: str(v) for k, v in attributes.items() if v is not None},
        }
        _model_call_counter.add(1, labels)
        _model_call_duration.record(duration_ms, labels)


def record_tool_call(
    agent_name: str,
    tool_name: str,
    duration_ms: float,
    success: bool = True,
    mcp_server: Optional[str] = None,
    **attributes: Any,
) -> None:
    """Record a tool call metric."""
    _ensure_instruments()
    if _tool_call_counter and _tool_call_duration:
        labels = {
            "agent.name": agent_name,
            "tool.name": tool_name,
            "success": str(success).lower(),
            **({"mcp.server": mcp_server} if mcp_server else {}),
            **{k: str(v) for k, v in attributes.items() if v is not None},
        }
        _tool_call_counter.add(1, labels)
        _tool_call_duration.record(duration_ms, labels)


def record_delegation(
    agent_name: str,
    target_agent: str,
    duration_ms: float,
    success: bool = True,
    **attributes: Any,
) -> None:
    """Record an A2A delegation metric."""
    _ensure_instruments()
    if _delegation_counter and _delegation_duration:
        labels = {
            "agent.name": agent_name,
            "target.agent": target_agent,
            "success": str(success).lower(),
            **{k: str(v) for k, v in attributes.items() if v is not None},
        }
        _delegation_counter.add(1, labels)
        _delegation_duration.record(duration_ms, labels)


def record_agentic_step(
    agent_name: str,
    step: int,
    step_type: str,  # "model", "tool", "delegation", "final"
    **attributes: Any,
) -> None:
    """Record an agentic loop step."""
    _ensure_instruments()
    if _agentic_steps:
        labels = {
            "agent.name": agent_name,
            "step": str(step),
            "step.type": step_type,
            **{k: str(v) for k, v in attributes.items() if v is not None},
        }
        _agentic_steps.add(1, labels)


def record_session_start(agent_name: str) -> None:
    """Record a new session starting."""
    _ensure_instruments()
    if _active_sessions:
        _active_sessions.add(1, {"agent.name": agent_name})


def record_session_end(agent_name: str) -> None:
    """Record a session ending."""
    _ensure_instruments()
    if _active_sessions:
        _active_sessions.add(-1, {"agent.name": agent_name})


@contextmanager
def timed_operation(
    operation_name: str,
) -> Iterator[Dict[str, Any]]:
    """Context manager for timing operations.

    Yields a dict that will be populated with duration_ms after the block.
    """
    result: Dict[str, Any] = {"start_time": time.perf_counter()}
    try:
        yield result
    finally:
        result["duration_ms"] = (time.perf_counter() - result["start_time"]) * 1000
