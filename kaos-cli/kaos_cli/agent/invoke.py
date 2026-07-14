"""KAOS Agent invoke command."""

import json
import subprocess
import sys
import time
import signal
import typer

from kaos_cli.cluster_http import local_service_url
from kaos_cli.config import load_config, session_token


REASON_TEXT = {
    "platform_grant_missing": "not granted",
    "user_grant_required": "user not in a granted group",
    "access-control unreachable": "access-control unavailable (failing closed)",
    "access_control_unreachable": "access-control unavailable (failing closed)",
    "missing token": "no valid identity",
    "missing_token": "no valid identity",
}


def plain_access_reason(reason: str) -> str:
    """Translate gateway reason codes into concise user-facing text."""
    normalized = reason.strip().lower()
    if normalized in REASON_TEXT:
        return REASON_TEXT[normalized]
    if "access-control" in normalized and "unreachable" in normalized:
        return REASON_TEXT["access-control unreachable"]
    if "missing" in normalized and "token" in normalized:
        return REASON_TEXT["missing token"]
    return reason.replace("_", " ") or "request permitted"


def _response_content(response) -> str:
    try:
        data = response.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return json.dumps(data, indent=2)
    except (ValueError, AttributeError):
        return response.text


def _access_control_ready(namespace: str) -> bool:
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "deployment/kaos-pdp",
            "-n",
            namespace,
            "-o",
            "jsonpath={.status.readyReplicas}/{.spec.replicas}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    ready, _, desired = result.stdout.partition("/")
    return bool(ready) and ready == desired and desired != "0"


def _invoke_gateway(name: str, namespace: str | None, message: str, user: str | None) -> None:
    """Invoke an agent through the configured gateway and print its verdict."""
    import httpx

    config = load_config()
    address = config["gateway"].get("address", "").rstrip("/")
    namespace = namespace or config.get("namespace") or "default"
    if not address:
        typer.echo("✗ denied — no gateway address configured")
        return
    token = session_token(config, user) if user else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with local_service_url(address) as local_address:
            response = httpx.post(
                f"{local_address}/{namespace}/agent/{name}/v1/chat/completions",
                headers=headers,
                json={"messages": [{"role": "user", "content": message}], "stream": False},
                timeout=120.0,
            )
    except (httpx.HTTPError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        return
    content = _response_content(response)
    if content:
        typer.echo(content)
    reason = response.headers.get("x-kaos-access-reason", "")
    allowed = response.status_code < 400
    if not reason:
        if response.status_code in (401, 403) and not token:
            reason = "missing token"
        elif response.status_code in (401, 403) and not _access_control_ready(namespace):
            reason = "access-control unreachable"
        elif response.status_code in (401, 403) and token:
            reason = "user_grant_required"
        elif response.status_code >= 500:
            reason = "access-control unreachable"
        else:
            reason = "request permitted" if allowed else f"HTTP {response.status_code}"
    mark = "✓ allowed" if allowed else "✗ denied"
    typer.echo(f"{mark} — {plain_access_reason(reason)}")


def _is_autonomous(name: str, namespace: str) -> bool:
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "agent",
            name,
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.config.autonomous.goal}",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def invoke_command(
    name: str,
    namespace: str | None,
    message: str,
    port: int,
    stream: bool,
    user: str | None = None,
) -> None:
    """Send a message to an Agent via port-forward."""
    import httpx

    config = load_config()
    configured_namespace = namespace or config.get("namespace") or "default"
    if user or (
        config["gateway"].get("through_gateway")
        and not _is_autonomous(name, configured_namespace)
    ):
        _invoke_gateway(name, namespace, message, user)
        return
    namespace = configured_namespace

    # Find the service for this Agent
    cmd = [
        "kubectl",
        "get",
        "svc",
        f"agent-{name}",
        "-o",
        "jsonpath={.spec.ports[0].port}",
    ]
    if namespace:
        cmd.extend(["-n", namespace])
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(f"Error: Agent '{name}' not found", err=True)
        sys.exit(1)

    svc_port = result.stdout.strip() or "8000"

    typer.echo(f"Port-forwarding to agent-{name}:{svc_port}...")

    # Start port-forward in background
    pf_cmd = ["kubectl", "port-forward", f"svc/agent-{name}", f"{port}:{svc_port}"]
    if namespace:
        pf_cmd.extend(["-n", namespace])
    pf_process = subprocess.Popen(
        pf_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    def cleanup():
        pf_process.terminate()
        pf_process.wait()

    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))

    time.sleep(2)

    if pf_process.poll() is not None:
        stderr = pf_process.stderr.read().decode() if pf_process.stderr else ""
        typer.echo(f"Error: Port-forward failed: {stderr}", err=True)
        sys.exit(1)

    try:
        typer.echo(f"Sending message: {message}")

        try:
            if stream:
                # Streaming response
                with httpx.stream(
                    "POST",
                    f"http://localhost:{port}/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": message}],
                        "stream": True,
                    },
                    timeout=120.0,
                ) as response:
                    typer.echo("\n📤 Response:")
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data != "[DONE]":
                                try:
                                    chunk = json.loads(data)
                                    if "choices" in chunk and chunk["choices"]:
                                        delta = chunk["choices"][0].get("delta", {})
                                        # Handle reasoning content (displayed before regular content)
                                        if "content" in delta:
                                            content = delta["content"]
                                            if content.startswith("{"):
                                                content = json.loads(content)
                                                typer.echo(f'Reasoning step {content["step"]}/{content["max_steps"]} | Action: {content["action"]} | Target: {content["target"]}')
                                            else:
                                                typer.echo(content, nl=False)
                                except json.JSONDecodeError:
                                    pass
                    typer.echo("")  # Final newline
            else:
                # Non-streaming
                response = httpx.post(
                    f"http://localhost:{port}/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": message}],
                        "stream": False,
                    },
                    timeout=120.0,
                )

                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and result["choices"]:
                        content = (
                            result["choices"][0].get("message", {}).get("content", "")
                        )
                        typer.echo("\n📤 Response:")
                        typer.echo(content)
                    else:
                        typer.echo(json.dumps(result, indent=2))
                    typer.echo("✓ allowed — request permitted")
                else:
                    typer.echo(
                        f"Error: HTTP {response.status_code}: {response.text}", err=True
                    )
        except httpx.ConnectError:
            typer.echo("Error: Could not connect to Agent", err=True)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
    finally:
        cleanup()
