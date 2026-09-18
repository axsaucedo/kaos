"""Tests for the deploy wait helper.

Regression cover for the create-then-wait race that failed the v0.7.5 and v0.7.6
release pipelines: `kubectl wait` returns NotFound immediately when the operator
has not created the Deployment yet, which aborted `kaos modelapi deploy --wait`.
"""

import subprocess
from unittest.mock import patch

from kaos_cli.utils.wait import wait_for_deployment_available


def _result(returncode: int, stderr: str = "", stdout: str = ""):
    return subprocess.CompletedProcess(
        args=["kubectl"], returncode=returncode, stdout=stdout, stderr=stderr
    )


NOT_FOUND = _result(
    1, stderr='Error from server (NotFound): deployments.apps "modelapi-x" not found\n'
)
AVAILABLE = _result(0, stdout="deployment.apps/modelapi-x condition met\n")
TIMED_OUT = _result(1, stderr="error: timed out waiting for the condition\n")


def test_retries_while_deployment_does_not_exist_yet():
    """The operator creating the Deployment late must not fail the command."""
    responses = [NOT_FOUND, NOT_FOUND, AVAILABLE]
    with patch("subprocess.run", side_effect=responses) as run:
        with patch("time.sleep"):
            result = wait_for_deployment_available("modelapi-x", "ns", 120)

    assert result.returncode == 0
    assert run.call_count == 3


def test_returns_immediately_once_available():
    with patch("subprocess.run", return_value=AVAILABLE) as run:
        result = wait_for_deployment_available("modelapi-x", "ns", 120)

    assert result.returncode == 0
    assert run.call_count == 1


def test_does_not_retry_on_a_real_condition_timeout():
    """A Deployment that exists but never goes available is a genuine failure."""
    with patch("subprocess.run", return_value=TIMED_OUT) as run:
        result = wait_for_deployment_available("modelapi-x", "ns", 120)

    assert result.returncode == 1
    assert run.call_count == 1


def test_gives_up_when_deployment_never_appears():
    """A Deployment that never shows up still fails, bounded by the timeout."""
    with patch("subprocess.run", return_value=NOT_FOUND) as run:
        with patch("time.sleep"):
            result = wait_for_deployment_available("modelapi-x", "ns", 0)

    assert result.returncode == 1
    assert "not found" in result.stderr
    assert run.call_count == 1


def test_passes_namespace_when_given():
    with patch("subprocess.run", return_value=AVAILABLE) as run:
        wait_for_deployment_available("modelapi-x", "my-ns", 120)

    args = run.call_args[0][0]
    assert args[:3] == ["kubectl", "wait", "deployment/modelapi-x"]
    assert "--for=condition=available" in args
    assert args[-2:] == ["-n", "my-ns"]


def test_omits_namespace_when_not_given():
    with patch("subprocess.run", return_value=AVAILABLE) as run:
        wait_for_deployment_available("modelapi-x", None, 120)

    assert "-n" not in run.call_args[0][0]


def test_timeout_shrinks_across_retries():
    """Each retry must pass kubectl the time that is actually left, never the full
    budget again, or the total wait could run to timeout x attempts."""
    clock = {"t": 0.0}

    def fake_monotonic():
        return clock["t"]

    def fake_sleep(seconds):
        clock["t"] += seconds

    with patch("subprocess.run", side_effect=[NOT_FOUND, NOT_FOUND, AVAILABLE]) as run:
        with patch("time.monotonic", side_effect=fake_monotonic):
            with patch("time.sleep", side_effect=fake_sleep):
                wait_for_deployment_available("modelapi-x", "ns", 100)

    timeouts = [
        next(a for a in call[0][0] if a.startswith("--timeout="))
        for call in run.call_args_list
    ]
    assert timeouts == ["--timeout=100s", "--timeout=98s", "--timeout=96s"]
