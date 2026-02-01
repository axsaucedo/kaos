"""KAOS Agent invoke command."""

import json
import subprocess
import sys
import time
import signal
import typer


def invoke_command(
    name: str,
    namespace: str | None,
    message: str,
    port: int,
    stream: bool,
) -> None:
    """Send a message to an Agent via port-forward."""
    import httpx

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
                                        if "content" in delta:
                                            typer.echo(delta["content"], nl=False)
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
