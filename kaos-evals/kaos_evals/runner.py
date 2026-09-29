"""Command-line orchestration for local KAOS evaluation runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic_ai.models import Model

from kaos_evals.contract import (
    CONTRACT_VERSION,
    EvalSuite,
    FailureKind,
    GateEvaluation,
    Provenance,
    RunResult,
    TargetSpec,
    Verdict,
    load_suite,
)
from kaos_evals.harness import run_suite
from kaos_evals.targets import HttpTarget, LocalTarget, TargetAdapter

EXIT_CODES = {Verdict.PASSED: 0, Verdict.FAILED: 1, Verdict.ERROR: 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a KAOS evaluation suite")
    parser.add_argument("--suite", default=os.getenv("KAOS_EVAL_SUITE"), required=False)
    parser.add_argument("--target-url", default=os.getenv("KAOS_EVAL_TARGET_URL"))
    parser.add_argument(
        "--target-mode",
        choices=("http", "local"),
        default=os.getenv("KAOS_EVAL_TARGET_MODE", "http"),
    )
    parser.add_argument("--target-model", default=os.getenv("KAOS_EVAL_TARGET_MODEL", "agent"))
    parser.add_argument(
        "--judge-base-url",
        action="append",
        default=[],
        metavar="MODEL=URL",
        help="OpenAI-compatible judge endpoint; repeat for multiple models",
    )
    parser.add_argument(
        "--summary-path",
        default=os.getenv("KAOS_EVAL_SUMMARY_PATH", "summary.json"),
    )
    parser.add_argument(
        "--report-path",
        default=os.getenv("KAOS_EVAL_REPORT_PATH", "report.json"),
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if not args.suite:
        build_parser().error("--suite or KAOS_EVAL_SUITE is required")
    if not args.target_url:
        build_parser().error("--target-url or KAOS_EVAL_TARGET_URL is required")
    return args


def _judge_base_urls(values: Sequence[str]) -> dict[str, str]:
    configured: dict[str, str] = {}
    env_value = os.getenv("KAOS_EVAL_JUDGE_BASE_URLS")
    if env_value:
        parsed = json.loads(env_value)
        if not isinstance(parsed, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
        ):
            raise ValueError("KAOS_EVAL_JUDGE_BASE_URLS must be a JSON object of model URLs")
        configured.update(parsed)
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid --judge-base-url {value!r}; expected MODEL=URL")
        model, url = value.split("=", 1)
        if not model or not url:
            raise ValueError(f"invalid --judge-base-url {value!r}; expected MODEL=URL")
        configured[model] = url
    return configured


def _judge_models(suite: EvalSuite) -> dict[str, str]:
    evaluators = list(suite.evaluators)
    for case in suite.cases:
        evaluators.extend(case.evaluators)
    return {
        evaluator.name: evaluator.config["model"]
        for evaluator in evaluators
        if evaluator.kind == "llm_judge"
    }


def _target_spec(args: argparse.Namespace) -> TargetSpec:
    return TargetSpec(mode=args.target_mode, url=args.target_url, model=args.target_model)


def _provenance(
    suite: EvalSuite,
    target: TargetSpec,
    started_at: datetime,
    judge_models: Mapping[str, str],
) -> Provenance:
    return Provenance(
        suite_hash=suite.suite_hash(),
        target=target,
        engine_version=version("pydantic-evals"),
        contract_version=CONTRACT_VERSION,
        judge_models=dict(judge_models),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


def _error_result(
    suite: EvalSuite,
    target: TargetSpec,
    started_at: datetime,
    judge_models: Mapping[str, str],
    error: Exception,
) -> RunResult:
    message = f"{type(error).__name__}: {error}"
    gate = GateEvaluation(
        verdict=Verdict.ERROR,
        pass_rate=0,
        passed_cases=0,
        total_cases=0,
        failed_rules=["run_error"],
        reasons=[message],
    )
    return RunResult(
        suite_name=suite.name,
        verdict=Verdict.ERROR,
        cases=[],
        gate=gate,
        provenance=_provenance(suite, target, started_at, judge_models),
        failure_kind=FailureKind.RUN_ERROR,
        error=message,
    )


def write_artifacts(result: RunResult, summary_path: str | Path, report_path: str | Path) -> None:
    summary = result.model_copy(update={"cases": []})
    for path, value in ((Path(summary_path), summary), (Path(report_path), result)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value.model_dump_json(by_alias=True, indent=2) + "\n")


async def execute(
    args: argparse.Namespace,
    *,
    target: TargetAdapter | Any | None = None,
    judge_models: Mapping[str, Model] | None = None,
) -> int:
    started_at = datetime.now(UTC)
    suite = load_suite(args.suite)
    target_spec = _target_spec(args)
    model_bindings = _judge_models(suite)
    base_urls = _judge_base_urls(args.judge_base_url)
    owned_target = target is None
    if target is None:
        target = (
            LocalTarget(
                url=args.target_url,
                model=args.target_model,
                timeout_seconds=suite.run.timeout_seconds,
            )
            if args.target_mode == "local"
            else HttpTarget(
                args.target_url,
                model=args.target_model,
                timeout_seconds=suite.run.timeout_seconds,
            )
        )
    try:
        try:
            result = await run_suite(
                suite,
                target,
                judge_base_urls=base_urls,
                judge_models=judge_models,
            )
            result.provenance = _provenance(suite, target_spec, started_at, model_bindings)
        except Exception as exc:
            result = _error_result(suite, target_spec, started_at, model_bindings, exc)
        write_artifacts(result, args.summary_path, args.report_path)
        print(
            json.dumps(
                {
                    "suite": result.suite_name,
                    "verdict": result.verdict,
                    "passedCases": result.gate.passed_cases,
                    "totalCases": result.gate.total_cases,
                }
            )
        )
        return EXIT_CODES[result.verdict]
    finally:
        close = getattr(target, "aclose", None)
        if owned_target and callable(close):
            await close()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(execute(parse_args(argv)))
    except Exception as exc:
        print(f"kaos-evals-runner: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
