"""Pydantic Evals engine boundary for KAOS suites and results."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext
from pydantic_evals.evaluators.llm_as_a_judge import (
    judge_input_output,
    judge_input_output_expected,
    judge_output,
    judge_output_expected,
)
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from kaos_evals.contract import (
    CaseResult,
    EvalCase,
    EvalSuite,
    EvaluatorKind,
    EvaluatorResult,
    EvaluatorSpec,
    FailureKind,
    RunResult,
)
from kaos_evals.gates import evaluate_gates


@dataclass
class HarnessOutput:
    output: Any
    duration_seconds: float = 0
    usage: dict[str, float | int] | None = None
    trace_id: str | None = None


@dataclass(repr=False)
class BuiltinEvaluator(Evaluator[EvalCase, HarnessOutput, dict[str, Any]]):
    spec: EvaluatorSpec

    def get_default_evaluation_name(self) -> str:
        return self.spec.name

    def evaluate(self, ctx: EvaluatorContext[EvalCase, HarnessOutput, dict[str, Any]]):
        output = ctx.output.output
        config = self.spec.config
        if self.spec.kind == EvaluatorKind.CONTAINS:
            expected = config["value"]
            actual = str(output)
            if not config.get("caseSensitive", True):
                expected, actual = expected.lower(), actual.lower()
            passed = expected in actual
            reason = f"output {'contains' if passed else 'does not contain'} {config['value']!r}"
        elif self.spec.kind == EvaluatorKind.EQUALS:
            passed = output == config["value"]
            reason = f"output {'equals' if passed else 'does not equal'} expected value"
        elif self.spec.kind == EvaluatorKind.REGEX:
            flags = 0
            for flag in config.get("flags", ""):
                flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}.get(flag, 0)
            passed = re.search(config["pattern"], str(output), flags) is not None
            reason = f"output {'matches' if passed else 'does not match'} {config['pattern']!r}"
        elif self.spec.kind == EvaluatorKind.IS_JSON:
            try:
                json.loads(output if isinstance(output, str) else json.dumps(output))
                passed, reason = True, "output is valid JSON"
            except (TypeError, ValueError):
                passed, reason = False, "output is not valid JSON"
        elif self.spec.kind == EvaluatorKind.MAX_DURATION:
            passed = ctx.output.duration_seconds <= float(config["seconds"])
            reason = (
                f"duration {ctx.output.duration_seconds:.3f}s "
                f"{'is within' if passed else 'exceeds'} {float(config['seconds']):.3f}s"
            )
        else:  # pragma: no cover - construction routes judges to JudgeEvaluator
            raise ValueError(f"unsupported evaluator kind: {self.spec.kind}")
        return EvaluationReason(value=passed, reason=reason)


@dataclass(repr=False)
class JudgeEvaluator(Evaluator[EvalCase, HarnessOutput, dict[str, Any]]):
    spec: EvaluatorSpec
    model: Model

    def get_default_evaluation_name(self) -> str:
        return self.spec.name

    async def evaluate(self, ctx: EvaluatorContext[EvalCase, HarnessOutput, dict[str, Any]]):
        config = self.spec.config
        output = ctx.output.output
        if config.get("includeInput"):
            if config.get("includeExpectedOutput"):
                grading = await judge_input_output_expected(
                    ctx.inputs.input,
                    output,
                    ctx.expected_output,
                    config["rubric"],
                    self.model,
                )
            else:
                grading = await judge_input_output(
                    ctx.inputs.input, output, config["rubric"], self.model
                )
        elif config.get("includeExpectedOutput"):
            grading = await judge_output_expected(
                output, ctx.expected_output, config["rubric"], self.model
            )
        else:
            grading = await judge_output(output, config["rubric"], self.model)
        if config.get("score"):
            return {
                self.spec.name: EvaluationReason(grading.score, grading.reason),
                f"{self.spec.name}_pass": EvaluationReason(grading.pass_, grading.reason),
            }
        return EvaluationReason(grading.pass_, grading.reason)


def build_judge_model(
    model_name: str,
    base_urls: Mapping[str, str] | None = None,
    models: Mapping[str, Model] | None = None,
) -> Model:
    if models and model_name in models:
        return models[model_name]
    base_url = (base_urls or {}).get(model_name)
    if not base_url:
        raise ValueError(f"no judge base URL configured for model {model_name!r}")
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=base_url, api_key="kaos-evals-local"),
    )


def build_evaluator(
    spec: EvaluatorSpec,
    *,
    judge_base_urls: Mapping[str, str] | None = None,
    judge_models: Mapping[str, Model] | None = None,
) -> Evaluator:
    if spec.kind == EvaluatorKind.LLM_JUDGE:
        model_name = spec.config.get("model")
        if not model_name:
            raise ValueError(f"judge evaluator {spec.name!r} requires an explicit model")
        return JudgeEvaluator(
            spec,
            build_judge_model(model_name, judge_base_urls, judge_models),
        )
    return BuiltinEvaluator(spec)


def build_dataset(
    suite: EvalSuite,
    *,
    judge_base_urls: Mapping[str, str] | None = None,
    judge_models: Mapping[str, Model] | None = None,
) -> Dataset:
    evaluators = [
        build_evaluator(
            evaluator,
            judge_base_urls=judge_base_urls,
            judge_models=judge_models,
        )
        for evaluator in suite.evaluators
    ]
    cases = [
        Case(
            name=case.id,
            inputs=case,
            metadata=case.metadata,
            expected_output=case.expected_output,
            evaluators=tuple(
                build_evaluator(
                    evaluator,
                    judge_base_urls=judge_base_urls,
                    judge_models=judge_models,
                )
                for evaluator in case.evaluators
            ),
        )
        for case in suite.cases
    ]
    return Dataset(name=suite.name, cases=cases, evaluators=evaluators)


def _map_evaluations(case: ReportCase) -> list[EvaluatorResult]:
    mapped: list[EvaluatorResult] = []
    for results in (case.scores, case.labels, case.assertions):
        for result in results.values():
            passed = result.value if isinstance(result.value, bool) else None
            mapped.append(
                EvaluatorResult(
                    name=result.name,
                    value=result.value,
                    passed=passed,
                    reason=result.reason,
                )
            )
    mapped.extend(
        EvaluatorResult(
            name=failure.name,
            reason=failure.error_message,
            failure_kind=FailureKind.EVALUATOR_INCONCLUSIVE,
        )
        for failure in case.evaluator_failures
    )
    return mapped


def _case_result(case: ReportCase) -> CaseResult:
    output = case.output
    evaluations = _map_evaluations(case)
    assertions = [result.passed for result in evaluations if result.passed is not None]
    inconclusive = bool(case.evaluator_failures)
    source = case.inputs
    return CaseResult(
        case_id=source.id,
        repetition=_repetition(case.name),
        tags=source.tags,
        output=output.output,
        duration_seconds=output.duration_seconds or case.task_duration,
        usage=output.usage or {},
        trace_id=output.trace_id or case.trace_id,
        evaluator_results=evaluations,
        passed=bool(assertions) and all(assertions) and not inconclusive,
        failure_kind=FailureKind.EVALUATOR_INCONCLUSIVE if inconclusive else None,
    )


def _failure_result(case: ReportCaseFailure) -> CaseResult:
    return CaseResult(
        case_id=case.inputs.id,
        repetition=_repetition(case.name),
        tags=case.inputs.tags,
        passed=False,
        failure_kind=FailureKind.CANDIDATE_ERROR,
        error=case.error_message,
        trace_id=case.trace_id,
    )


def _repetition(name: str) -> int:
    match = re.search(r"\[(\d+)/(\d+)\]$", name)
    return int(match.group(1)) if match else 1


def report_to_run_result(suite: EvalSuite, report: EvaluationReport) -> RunResult:
    cases = [_case_result(case) for case in report.cases]
    cases.extend(_failure_result(case) for case in report.failures)
    gate = evaluate_gates(cases, suite.gates)
    return RunResult(
        suite_name=suite.name,
        verdict=gate.verdict,
        cases=cases,
        gate=gate,
    )


async def run_suite(
    suite: EvalSuite,
    target: Callable[[EvalCase], Any],
    *,
    judge_base_urls: Mapping[str, str] | None = None,
    judge_models: Mapping[str, Model] | None = None,
) -> RunResult:
    dataset = build_dataset(
        suite,
        judge_base_urls=judge_base_urls,
        judge_models=judge_models,
    )

    async def task(case: EvalCase) -> HarnessOutput:
        response = target(case)
        if hasattr(response, "__await__"):
            response = await response
        if isinstance(response, HarnessOutput):
            return response
        if hasattr(response, "output"):
            return HarnessOutput(
                output=response.output,
                duration_seconds=getattr(response, "duration_seconds", 0),
                usage=getattr(response, "usage", None),
                trace_id=getattr(response, "trace_id", None),
            )
        return HarnessOutput(output=response)

    report = await dataset.evaluate(
        task,
        max_concurrency=suite.run.max_concurrency,
        repeat=suite.run.repeat,
        progress=False,
    )
    return report_to_run_result(suite, report)


__all__ = [
    "HarnessOutput",
    "build_dataset",
    "build_evaluator",
    "build_judge_model",
    "report_to_run_result",
    "run_suite",
]
