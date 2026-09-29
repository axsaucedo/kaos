import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from kaos_evals.contract import EvalSuite
from kaos_evals.harness import run_suite
from tests._fakes import FakeTargetResponse


@pytest.mark.asyncio
async def test_eval_span_topology_events_and_case_trace_id():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    suite = EvalSuite.model_validate(
        {
            "name": "telemetry",
            "evaluators": [{"name": "greeting", "kind": "contains", "config": {"value": "Hello"}}],
            "cases": [{"id": "one", "prompt": "Say hello"}],
        }
    )

    result = await run_suite(suite, lambda case: FakeTargetResponse("Hello"))

    spans = {
        span.name: span for span in exporter.get_finished_spans() if span.name.startswith("kaos.")
    }
    run = spans["kaos.eval.run"]
    case = spans["kaos.eval.case"]
    evaluator = spans["kaos.eval.evaluator"]
    assert case.parent is not None
    assert evaluator.parent is not None
    assert case.parent.span_id == run.context.span_id
    assert evaluator.parent.span_id == case.context.span_id
    assert result.cases[0].trace_id == f"{run.context.trace_id:032x}"
    event = evaluator.events[0]
    assert event.attributes is not None
    assert event.name == "gen_ai.evaluation.result"
    assert event.attributes["gen_ai.evaluation.name"] == "greeting"
    assert event.attributes["gen_ai.evaluation.result"] is True
    assert "contains" in str(event.attributes["gen_ai.evaluation.reason"])
