import asyncio
import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from kaos_evals.contract import EvalSuite, Verdict
from kaos_evals.harness import build_dataset, build_judge_model, run_suite
from tests._fakes import FakeTargetResponse


def judge_model():
    def handler(messages, info):
        return ModelResponse(
            parts=[
                TextPart(
                    json.dumps(
                        {
                            "reason": "The output meets the rubric.",
                            "pass": True,
                            "score": 0.95,
                        }
                    )
                )
            ]
        )

    return FunctionModel(handler)


def suite(repeat=1, max_concurrency=2):
    output = '{"answer":"hello"}'
    return EvalSuite.model_validate(
        {
            "name": "builtins",
            "evaluators": [
                {"name": "contains", "kind": "contains", "config": {"value": "hello"}},
                {"name": "equals", "kind": "equals", "config": {"value": output}},
                {"name": "regex", "kind": "regex", "config": {"pattern": "answer.*hello"}},
                {"name": "json", "kind": "is_json"},
                {"name": "fast", "kind": "max_duration", "config": {"seconds": 1}},
                {
                    "name": "judge",
                    "kind": "llm_judge",
                    "config": {"rubric": "Contains a greeting", "model": "test", "score": True},
                },
            ],
            "cases": [{"id": "one", "prompt": "hello"}, {"id": "two", "prompt": "hello"}],
            "gates": {"thresholds": {"judge": 0.9}},
            "run": {"repeat": repeat, "maxConcurrency": max_concurrency},
        }
    )


def test_dataset_maps_all_builtin_evaluator_kinds():
    dataset = build_dataset(suite(), judge_models={"test": judge_model()})

    assert len(dataset.evaluators) == 6
    assert len(dataset.cases) == 2


@pytest.mark.asyncio
async def test_harness_maps_engine_report_to_contract_without_engine_types():
    result = await run_suite(
        suite(),
        lambda case: FakeTargetResponse(
            '{"answer":"hello"}',
            duration_seconds=0.2,
            usage={"total_tokens": 4},
            trace_id="a" * 32,
        ),
        judge_models={"test": judge_model()},
    )

    assert result.verdict == Verdict.PASSED
    assert len(result.cases) == 2
    assert {item.name for item in result.cases[0].evaluator_results} == {
        "contains",
        "equals",
        "regex",
        "json",
        "fast",
        "judge",
        "judge_pass",
    }
    assert result.cases[0].trace_id == "a" * 32
    assert result.cases[0].usage == {"total_tokens": 4}
    assert "pydantic_evals" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_concurrency_and_repetition_are_passed_to_engine():
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def target(case):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(active, max_active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return '{"answer":"hello"}'

    result = await run_suite(
        suite(repeat=2, max_concurrency=2), target, judge_models={"test": judge_model()}
    )

    assert len(result.cases) == 4
    assert max_active == 2
    assert {item.repetition for item in result.cases} == {1, 2}


def test_judge_model_fails_closed_without_explicit_base_url():
    with pytest.raises(ValueError, match="no judge base URL configured"):
        build_judge_model("missing")
