import json

import pytest

from kaos_evals.contract import RunResult, Verdict
from kaos_evals.runner import execute, parse_args
from kaos_evals.targets import LocalTarget
from pais.server import create_agent_server
from pais.serverutils import AgentServerSettings


@pytest.mark.asyncio
async def test_real_agent_server_runs_suite_through_local_target(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBUG_MOCK_RESPONSES", json.dumps(["Hello from eval agent"]))
    settings = AgentServerSettings(
        agent_name="eval-agent",
        memory_enabled=False,
        task_store_type="null",
    )
    server = create_agent_server(settings)
    target = LocalTarget(server.app)
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("""name: agent-server-smoke
evaluators:
  - name: exact
    kind: equals
    config:
      value: Hello from eval agent
cases:
  - id: greeting
    prompt: Say hello
gates:
  minPassRate: 1
""")
    summary_path = tmp_path / "summary.json"
    report_path = tmp_path / "report.json"
    args = parse_args(
        [
            "--suite",
            str(suite_path),
            "--target-mode",
            "local",
            "--target-url",
            "http://kaos-local",
            "--summary-path",
            str(summary_path),
            "--report-path",
            str(report_path),
        ]
    )

    try:
        exit_code = await execute(args, target=target)
    finally:
        await target.aclose()

    report = RunResult.model_validate_json(report_path.read_text())
    summary = RunResult.model_validate_json(summary_path.read_text())
    assert exit_code == 0
    assert report.verdict == Verdict.PASSED
    assert report.cases[0].case_id == "greeting"
    assert report.cases[0].output == "Hello from eval agent"
    assert report.cases[0].passed is True
    assert report.cases[0].evaluator_results[0].name == "exact"
    assert summary.verdict == Verdict.PASSED
    assert summary.cases == []
