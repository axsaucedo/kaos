import json

import pytest

from kaos_evals.contract import RunResult, Verdict
from kaos_evals.runner import execute, parse_args
from tests._fakes import FakeTargetResponse


def write_suite(path, *, evaluator=None, gates=None):
    suite = {
        "name": "runner-test",
        "evaluators": [evaluator] if evaluator else [],
        "cases": [{"id": "case", "prompt": "Say hello"}],
        "gates": gates or {},
    }
    path.write_text(json.dumps(suite))


def args(tmp_path, suite_path):
    return parse_args(
        [
            "--suite",
            str(suite_path),
            "--target-url",
            "http://fake-agent",
            "--summary-path",
            str(tmp_path / "summary.json"),
            "--report-path",
            str(tmp_path / "report.json"),
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expected", "target_output", "exit_code", "verdict"),
    [
        ("Hello", "Hello", 0, Verdict.PASSED),
        ("Hello", "Goodbye", 1, Verdict.FAILED),
    ],
)
async def test_runner_writes_contract_artifacts_for_pass_and_failure(
    tmp_path, expected, target_output, exit_code, verdict
):
    suite_path = tmp_path / "suite.json"
    write_suite(
        suite_path,
        evaluator={"name": "exact", "kind": "equals", "config": {"value": expected}},
    )

    code = await execute(
        args(tmp_path, suite_path),
        target=lambda case: FakeTargetResponse(target_output, duration_seconds=0.01),
    )

    report = RunResult.model_validate_json((tmp_path / "report.json").read_text())
    summary = RunResult.model_validate_json((tmp_path / "summary.json").read_text())
    assert code == exit_code
    assert report.verdict == verdict
    assert report.provenance is not None
    assert report.provenance.suite_hash
    assert report.provenance.engine_version == "2.11.0"
    assert summary.verdict == verdict
    assert summary.cases == []


@pytest.mark.asyncio
async def test_runner_returns_error_when_gate_is_undecidable(tmp_path):
    suite_path = tmp_path / "suite.json"
    write_suite(suite_path, gates={"minPassRate": 0, "thresholds": {"missing": 0.5}})

    code = await execute(
        args(tmp_path, suite_path),
        target=lambda case: FakeTargetResponse("Hello"),
    )

    report = RunResult.model_validate_json((tmp_path / "report.json").read_text())
    assert code == 2
    assert report.verdict == Verdict.ERROR


@pytest.mark.asyncio
async def test_runner_records_run_errors_and_judge_provenance(tmp_path):
    suite_path = tmp_path / "suite.json"
    write_suite(
        suite_path,
        evaluator={
            "name": "judge",
            "kind": "llm_judge",
            "config": {"rubric": "Good", "model": "missing"},
        },
    )

    code = await execute(
        args(tmp_path, suite_path),
        target=lambda case: FakeTargetResponse("Hello"),
    )

    report = RunResult.model_validate_json((tmp_path / "report.json").read_text())
    assert code == 2
    assert report.error is not None
    assert report.provenance is not None
    assert report.error.startswith("ValueError: no judge base URL")
    assert report.provenance.judge_models == {"judge": "missing"}
