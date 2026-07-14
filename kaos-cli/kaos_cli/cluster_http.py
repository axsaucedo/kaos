"""HTTP access to cluster-local services from the host CLI."""

from contextlib import contextmanager
import socket
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit


def _gateway_service(namespace: str) -> tuple[str, str]:
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "service",
            "--all-namespaces",
            "-l",
            "gateway.envoyproxy.io/owning-gateway-name=kaos-gateway,"
            f"gateway.envoyproxy.io/owning-gateway-namespace={namespace}",
            "-o",
            "jsonpath={.items[0].metadata.namespace} {.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
    )
    parts = result.stdout.split()
    if result.returncode != 0 or len(parts) != 2:
        raise RuntimeError(result.stderr.strip() or "KAOS gateway service not found")
    return parts[1], parts[0]


@contextmanager
def local_service_url(url: str):
    """Yield a host-reachable URL, forwarding Kubernetes services as needed."""
    parsed = urlsplit(url)
    labels = (parsed.hostname or "").split(".")
    if len(labels) < 4 or labels[2:4] != ["svc", "cluster"]:
        yield url
        return

    service, namespace = labels[:2]
    if service == "kaos-gateway":
        service, namespace = _gateway_service(namespace)
    remote_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        local_port = listener.getsockname()[1]

    process = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "-n",
            namespace,
            f"service/{service}",
            f"{local_port}:{remote_port}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(50):
            if process.poll() is not None:
                stderr = process.stderr.read().decode() if process.stderr else ""
                raise RuntimeError(stderr.strip() or "kubectl port-forward failed")
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("timed out waiting for kubectl port-forward")

        yield urlunsplit(
            (parsed.scheme, f"127.0.0.1:{local_port}", parsed.path, parsed.query, parsed.fragment)
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
