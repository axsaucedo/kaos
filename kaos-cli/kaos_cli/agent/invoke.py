"""KAOS Agent invoke command."""

import json
import subprocess
import sys
import time
import signal
import typer

from kaos_cli.cluster_http import local_service_url
from kaos_cli.config import load_config, session_token
from kaos_cli.utils import current_context_namespace
from kaos_cli.auth.consent import (
    active_service_alias,
    reauth_url,
    service_alias,
    service_id_from_reauth_url,
)


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
    approval_url = reauth_url(response)
    if approval_url:
        service_id = service_id_from_reauth_url(approval_url)
        try:
            service = service_alias(config, service_id or "")
        except (httpx.HTTPError, RuntimeError, ValueError):
            service = "service"
        typer.echo(
            f"✗ needs approval — run: kaos auth connect {service} --user {user}"
        )
        return
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
    if allowed and user:
        try:
            service = active_service_alias(config, user, message)
        except (httpx.HTTPError, RuntimeError, ValueError):
            service = None
        if service:
            typer.echo(f"✓ allowed — acting as {user} on {service}")
            return
    mark = "✓ allowed" if allowed else "✗ denied"
    typer.echo(f"{mark} — {plain_access_reason(reason)}")


def _is_autonomous(name: str, namespace: str | None) -> bool:
    cmd = [
        "kubectl",
        "get",
        "agent",
        name,
        "-o",
        "jsonpath={.spec.config.autonomous.goal}",
    ]
    if namespace:
        cmd.extend(["-n", namespace])
    result = subprocess.run(cmd, capture_output=True, text=True)
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
    direct_namespace = namespace or current_context_namespace()
    if user or (
        config["gateway"].get("through_gateway")
        and not _is_autonomous(name, direct_namespace)
    ):
        _invoke_gateway(name, namespace, message, user)
        return
    namespace = direct_namespace

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

    try:
        last_error = "port-forward did not become ready"
        for _ in range(90):
            if pf_process.poll() is not None:
                stderr = pf_process.stderr.read().decode() if pf_process.stderr else ""
                typer.echo(f"Error: Port-forward failed: {stderr}", err=True)
                sys.exit(1)
            try:
                health = httpx.get(f"http://localhost:{port}/health", timeout=2.0)
                if health.status_code == 200:
                    break
                last_error = f"HTTP {health.status_code}"
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(1)
        else:
            typer.echo(f"Error: Could not connect to Agent: {last_error}", err=True)
            sys.exit(1)

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
            sys.exit(1)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
    finally:
        cleanup()
