"""Shared kubectl port-forward lifecycle and readiness handling."""

from contextlib import contextmanager
import socket
import subprocess
import time
from collections.abc import Iterator

import httpx


class PortForwardError(RuntimeError):
    """Raised when a kubectl port-forward cannot become ready."""


def _free_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def port_forward(
    target: str,
    remote_port: int,
    namespace: str | None,
    health_path: str,
    *,
    local_port: int | None = None,
    attempts: int = 90,
) -> Iterator[str]:
    """Forward a Kubernetes target and yield its ready localhost base URL."""
    local_port = local_port or _free_local_port()
    cmd = ["kubectl", "port-forward"]
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend([target, f"{local_port}:{remote_port}"])
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base_url = f"http://127.0.0.1:{local_port}"

    try:
        last_error = "port-forward did not become ready"
        for _ in range(attempts):
            if process.poll() is not None:
                stderr = process.stderr.read().decode() if process.stderr else ""
                raise PortForwardError(stderr.strip() or "kubectl port-forward exited")
            try:
                response = httpx.get(f"{base_url}{health_path}", timeout=2.0)
                if response.status_code == 200:
                    break
                last_error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(1)
        else:
            raise PortForwardError(last_error)

        yield base_url
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
