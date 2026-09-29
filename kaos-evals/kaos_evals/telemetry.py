"""No-op-safe OpenTelemetry helpers for evaluation runs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span

TRACER_NAME = "kaos.evals"


@contextmanager
def run_span(suite_name: str) -> Iterator[Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(
        "kaos.eval.run", attributes={"kaos.eval.suite.name": suite_name}
    ) as span:
        yield span


@contextmanager
def case_span(case_id: str, repetition: int, parent_context: Any) -> Iterator[Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(
        "kaos.eval.case",
        context=parent_context,
        attributes={
            "kaos.eval.case.id": case_id,
            "kaos.eval.case.repetition": repetition,
        },
    ) as span:
        yield span


@contextmanager
def evaluator_span(name: str, parent_context: Any) -> Iterator[Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(
        "kaos.eval.evaluator",
        context=parent_context,
        attributes={"gen_ai.evaluation.name": name},
    ) as span:
        yield span


def record_evaluation_result(span: Span, name: str, value: Any, reason: str | None) -> None:
    attributes: dict[str, bool | int | float | str] = {"gen_ai.evaluation.name": name}
    if isinstance(value, (bool, int, float, str)):
        attributes["gen_ai.evaluation.result"] = value
    if reason:
        attributes["gen_ai.evaluation.reason"] = reason
    span.add_event("gen_ai.evaluation.result", attributes)


def current_context() -> Any:
    return otel_context.get_current()


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


__all__ = [
    "case_span",
    "current_context",
    "current_trace_id",
    "evaluator_span",
    "record_evaluation_result",
    "run_span",
]
