import pytest

from kaos_evals.contract import (
    CaseResult,
    EvaluatorResult,
    FailureKind,
    GateSpec,
    Verdict,
)
from kaos_evals.gates import evaluate_gates


def case(
    case_id="case",
    *,
    passed=True,
    tags=None,
    duration=0,
    usage=None,
    evaluator_results=None,
    failure_kind=None,
):
    return CaseResult(
        case_id=case_id,
        passed=passed,
        tags=tags or [],
        duration_seconds=duration,
        usage=usage or {},
        evaluator_results=evaluator_results or [],
        failure_kind=failure_kind,
    )


def test_minimum_pass_rate():
    result = evaluate_gates(
        [case("pass"), case("fail", passed=False)], GateSpec(min_pass_rate=0.75)
    )

    assert result.verdict == Verdict.FAILED
    assert result.pass_rate == 0.5
    assert result.failed_rules == ["minPassRate"]


@pytest.mark.parametrize(
    ("values", "verdict"),
    [([0.9, 0.7], Verdict.PASSED), ([0.9, 0.5], Verdict.FAILED)],
)
def test_per_evaluator_threshold(values, verdict):
    cases = [
        case(
            str(index),
            evaluator_results=[EvaluatorResult(name="quality", value=value, passed=True)],
        )
        for index, value in enumerate(values)
    ]

    assert evaluate_gates(cases, GateSpec(thresholds={"quality": 0.75})).verdict == verdict


def test_critical_tag_requires_every_matching_case_to_pass():
    result = evaluate_gates(
        [case("normal"), case("must-work", passed=False, tags=["critical"])],
        GateSpec(min_pass_rate=0.5, critical_tags=["critical"]),
    )

    assert result.verdict == Verdict.FAILED
    assert "criticalTags" in result.failed_rules


@pytest.mark.parametrize(
    ("spec", "rule"),
    [
        (GateSpec(max_total_duration_seconds=1), "maxTotalDurationSeconds"),
        (GateSpec(max_total_tokens=10), "maxTotalTokens"),
        (GateSpec(max_total_cost_usd=0.1), "maxTotalCostUsd"),
    ],
)
def test_budget_ceilings(spec, rule):
    result = evaluate_gates([case(duration=2, usage={"total_tokens": 11, "cost_usd": 0.2})], spec)

    assert result.verdict == Verdict.FAILED
    assert rule in result.failed_rules


def test_candidate_error_is_a_case_failure():
    result = evaluate_gates(
        [case(passed=False, failure_kind=FailureKind.CANDIDATE_ERROR)],
        GateSpec(),
    )

    assert result.verdict == Verdict.FAILED
    assert result.pass_rate == 0


def test_inconclusive_case_is_excluded_and_can_make_gate_undecidable():
    result = evaluate_gates(
        [
            case(
                passed=False,
                failure_kind=FailureKind.EVALUATOR_INCONCLUSIVE,
                evaluator_results=[
                    EvaluatorResult(
                        name="quality",
                        failure_kind=FailureKind.EVALUATOR_INCONCLUSIVE,
                        reason="judge unavailable",
                    )
                ],
            )
        ],
        GateSpec(thresholds={"quality": 0.8}),
    )

    assert result.verdict == Verdict.ERROR
    assert "inconclusive" in result.failed_rules


def test_conclusive_failure_dominates_evaluator_uncertainty():
    result = evaluate_gates(
        [
            case("failed", passed=False),
            case("unknown", passed=False, failure_kind=FailureKind.EVALUATOR_INCONCLUSIVE),
        ],
        GateSpec(min_pass_rate=1),
    )

    assert result.verdict == Verdict.FAILED


def test_run_error_dominates_conclusive_failure():
    result = evaluate_gates(
        [case(passed=False, failure_kind=FailureKind.CANDIDATE_ERROR)],
        GateSpec(),
        run_error="suite execution crashed",
    )

    assert result.verdict == Verdict.ERROR
    assert result.failed_rules == ["run_error"]


def test_critical_inconclusive_case_is_an_error():
    result = evaluate_gates(
        [
            case(
                "critical",
                passed=False,
                tags=["critical"],
                failure_kind=FailureKind.EVALUATOR_INCONCLUSIVE,
            )
        ],
        GateSpec(critical_tags=["critical"]),
    )

    assert result.verdict == Verdict.ERROR
