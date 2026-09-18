"""Wait helpers for resources the operator creates asynchronously."""

import subprocess
import time


NOT_FOUND_POLL_INTERVAL = 2


def _is_not_found(result: subprocess.CompletedProcess) -> bool:
    """Return True when kubectl failed only because the object does not exist yet."""
    message = f"{result.stderr}{result.stdout}".lower()
    return "notfound" in message or "not found" in message


def wait_for_deployment_available(
    deployment: str,
    namespace: str | None,
    timeout: int,
) -> subprocess.CompletedProcess:
    """Wait for a Deployment to exist and report condition=available.

    `kubectl wait` resolves the object once, up front: if it is not there yet the
    command fails immediately with NotFound, and --timeout only bounds waiting for
    the condition on an object that already exists. The Deployments waited on here
    are created by the operator in response to a custom resource, so calling
    `kubectl wait` straight after `kubectl apply` races the operator's first
    reconcile and loses whenever the reconcile lands a moment later.

    Retry while the Deployment is still absent, and let `kubectl wait` handle the
    condition itself once it appears. `timeout` bounds the whole operation, so a
    Deployment that never appears fails after the same total wait as one that
    appears but never becomes available.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        args = [
            "kubectl",
            "wait",
            f"deployment/{deployment}",
            "--for=condition=available",
            f"--timeout={max(1, int(remaining))}s",
        ]
        if namespace:
            args.extend(["-n", namespace])
        result = subprocess.run(args, capture_output=True, text=True)

        if result.returncode == 0 or not _is_not_found(result):
            return result

        # The Deployment has not been created yet. Retry until the deadline.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result
        time.sleep(min(NOT_FOUND_POLL_INTERVAL, remaining))
