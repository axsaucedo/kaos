"""Pure gate evaluation over KAOS result models."""

from __future__ import annotations

from kaos_evals.contract import (
    CaseResult,
    FailureKind,
    GateEvaluation,
    GateSpec,
    Verdict,
)


def evaluate_gates(
    cases: list[CaseResult],
    spec: GateSpec,
    *,
    run_error: str | None = None,
) -> GateEvaluation:
    """Evaluate every configured gate without engine-specific state."""
    if run_error:
        return GateEvaluation(
            verdict=Verdict.ERROR,
            pass_rate=0,
            passed_cases=0,
            total_cases=len(cases),
            failed_rules=["run_error"],
            reasons=[run_error],
        )

    failed_rules: list[str] = []
    reasons: list[str] = []
    undecidable: list[str] = []
    conclusive_cases = [
        case for case in cases if case.failure_kind != FailureKind.EVALUATOR_INCONCLUSIVE
    ]
    passed_cases = sum(case.passed for case in conclusive_cases)
    pass_rate = passed_cases / len(conclusive_cases) if conclusive_cases else 0

    if not conclusive_cases and cases:
        undecidable.append("minPassRate has no conclusive case results")
    elif pass_rate < spec.min_pass_rate:
        failed_rules.append("minPassRate")
        reasons.append(f"case pass rate {pass_rate:.3f} is below required {spec.min_pass_rate:.3f}")

    for name, threshold in spec.thresholds.items():
        values: list[float] = []
        inconclusive = False
        for case in cases:
            for result in case.evaluator_results:
                if result.name != name:
                    continue
                if result.failure_kind == FailureKind.EVALUATOR_INCONCLUSIVE:
                    inconclusive = True
                elif isinstance(result.value, bool):
                    values.append(float(result.value))
                elif isinstance(result.value, (int, float)):
                    values.append(float(result.value))
                elif result.passed is not None:
                    values.append(float(result.passed))
                else:
                    inconclusive = True
        if not values:
            undecidable.append(f"thresholds.{name} has no conclusive evaluator results")
            continue
        aggregate = sum(values) / len(values)
        if aggregate < threshold:
            failed_rules.append(f"thresholds.{name}")
            reasons.append(
                f"evaluator {name} aggregate {aggregate:.3f} is below required {threshold:.3f}"
            )
        elif inconclusive:
            reasons.append(f"evaluator {name} excluded inconclusive results")

    critical = set(spec.critical_tags)
    for case in cases:
        if not critical.intersection(case.tags):
            continue
        if case.failure_kind == FailureKind.EVALUATOR_INCONCLUSIVE:
            undecidable.append(f"critical case {case.case_id} is inconclusive")
        elif not case.passed:
            failed_rules.append("criticalTags")
            reasons.append(f"critical case {case.case_id} failed")

    total_duration = sum(case.duration_seconds for case in cases)
    if (
        spec.max_total_duration_seconds is not None
        and total_duration > spec.max_total_duration_seconds
    ):
        failed_rules.append("maxTotalDurationSeconds")
        reasons.append(
            f"total duration {total_duration:.3f}s exceeds {spec.max_total_duration_seconds:.3f}s"
        )

    total_tokens = sum(int(case.usage.get("total_tokens", 0)) for case in cases)
    if spec.max_total_tokens is not None and total_tokens > spec.max_total_tokens:
        failed_rules.append("maxTotalTokens")
        reasons.append(f"total tokens {total_tokens} exceeds {spec.max_total_tokens}")

    total_cost = sum(float(case.usage.get("cost_usd", 0)) for case in cases)
    if spec.max_total_cost_usd is not None and total_cost > spec.max_total_cost_usd:
        failed_rules.append("maxTotalCostUsd")
        reasons.append(f"total cost ${total_cost:.6f} exceeds ${spec.max_total_cost_usd:.6f}")

    if failed_rules:
        verdict = Verdict.FAILED
    elif undecidable:
        verdict = Verdict.ERROR
        failed_rules.extend("inconclusive" for _ in undecidable)
        reasons.extend(undecidable)
    else:
        verdict = Verdict.PASSED

    return GateEvaluation(
        verdict=verdict,
        pass_rate=pass_rate,
        passed_cases=passed_cases,
        total_cases=len(cases),
        failed_rules=failed_rules,
        reasons=reasons,
    )


__all__ = ["evaluate_gates"]
