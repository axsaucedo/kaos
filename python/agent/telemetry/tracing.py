"""
Tracing utilities for KAOS agents.

Provides span creation, context propagation, and semantic conventions
for agent processing, model calls, tool execution, and A2A delegation.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from opentelemetry import trace
from opentelemetry.propagate import inject, extract
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.context import Context

logger = logging.getLogger(__name__)

# Semantic conventions for KAOS spans
AGENT_NAME = "agent.name"
AGENT_STEP = "agent.step"
AGENT_MAX_STEPS = "agent.max_steps"
SESSION_ID = "session.id"
MODEL_NAME = "gen_ai.request.model"
MODEL_PROVIDER = "gen_ai.system"
TOOL_NAME = "tool.name"
TOOL_ARGUMENTS = "tool.arguments"
DELEGATION_TARGET = "agent.delegation.target"
DELEGATION_TASK = "agent.delegation.task"
MESSAGE_ROLE = "gen_ai.message.role"
MESSAGE_CONTENT_LENGTH = "gen_ai.message.content_length"
PROMPT_TOKENS = "gen_ai.usage.prompt_tokens"
COMPLETION_TOKENS = "gen_ai.usage.completion_tokens"

# Tracer name for KAOS components
TRACER_NAME = "kaos.agent"


def get_tracer(name: str = TRACER_NAME) -> trace.Tracer:
    """Get a tracer for creating spans."""
    return trace.get_tracer(name)


def get_current_span() -> Optional[Span]:
    """Get the current active span."""
    span = trace.get_current_span()
    return span if span.is_recording() else None


def inject_context(carrier: Dict[str, str]) -> Dict[str, str]:
    """Inject current trace context into a carrier (e.g., HTTP headers).

    Used for propagating context to downstream services.
    """
    inject(carrier)
    return carrier


def extract_context(carrier: Dict[str, str]) -> Context:
    """Extract trace context from a carrier (e.g., HTTP headers).

    Used for receiving context from upstream services.
    """
    return extract(carrier)


@contextmanager
def span_attributes(span: Optional[Span], **attributes: Any) -> Iterator[None]:
    """Context manager to add attributes to a span if it exists."""
    if span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
    yield


def create_agent_span(
    name: str,
    agent_name: str,
    session_id: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    **attributes: Any,
) -> Span:
    """Create a span for agent operations."""
    tracer = get_tracer()
    span = tracer.start_span(
        name,
        kind=kind,
        attributes={
            AGENT_NAME: agent_name,
            **({"session.id": session_id} if session_id else {}),
            **{k: v for k, v in attributes.items() if v is not None},
        },
    )
    return span


def create_model_span(
    model_name: str,
    agent_name: str,
    step: int,
    **attributes: Any,
) -> Span:
    """Create a span for model API calls."""
    tracer = get_tracer()
    return tracer.start_span(
        "model.inference",
        kind=SpanKind.CLIENT,
        attributes={
            MODEL_NAME: model_name,
            AGENT_NAME: agent_name,
            AGENT_STEP: step,
            **{k: v for k, v in attributes.items() if v is not None},
        },
    )


def create_tool_span(
    tool_name: str,
    agent_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    **attributes: Any,
) -> Span:
    """Create a span for tool execution."""
    tracer = get_tracer()
    return tracer.start_span(
        f"tool.{tool_name}",
        kind=SpanKind.CLIENT,
        attributes={
            TOOL_NAME: tool_name,
            AGENT_NAME: agent_name,
            **({"tool.arguments": str(arguments)} if arguments else {}),
            **{k: v for k, v in attributes.items() if v is not None},
        },
    )


def create_delegation_span(
    target_agent: str,
    task: str,
    agent_name: str,
    **attributes: Any,
) -> Span:
    """Create a span for A2A delegation."""
    tracer = get_tracer()
    return tracer.start_span(
        f"delegate.{target_agent}",
        kind=SpanKind.CLIENT,
        attributes={
            DELEGATION_TARGET: target_agent,
            DELEGATION_TASK: task[:500],  # Truncate long tasks
            AGENT_NAME: agent_name,
            **{k: v for k, v in attributes.items() if v is not None},
        },
    )


def end_span_ok(span: Span, message: Optional[str] = None) -> None:
    """End a span with OK status."""
    span.set_status(Status(StatusCode.OK, message))
    span.end()


def end_span_error(span: Span, error: Exception) -> None:
    """End a span with ERROR status and record the exception."""
    span.set_status(Status(StatusCode.ERROR, str(error)))
    span.record_exception(error)
    span.end()
