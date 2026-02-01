"""KAOS ModelAPI invoke command."""

import json
import subprocess
import sys
import time
import signal
import typer


def invoke_command(
    name: str,
    namespace: str,
    message: str,
    model: str,
    port: int,
) -> None:
    """Send a chat completion request to a ModelAPI via port-forward."""
    import httpx

    # Find the service for this ModelAPI
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "svc",
            f"modelapi-{name}",
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.ports[0].port}",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        typer.echo(
            f"Error: ModelAPI '{name}' not found in namespace '{namespace}'", err=True
        )
        sys.exit(1)

    svc_port = result.stdout.strip() or "8000"

    typer.echo(f"Port-forwarding to modelapi-{name}:{svc_port}...")

    # Start port-forward in background
    pf_process = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/modelapi-{name}",
            f"{port}:{svc_port}",
            "-n",
            namespace,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
        typer.echo(f"Sending message to model '{model}': {message}")

        try:
            response = httpx.post(
                f"http://localhost:{port}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": message}],
                    "stream": False,
                },
                timeout=120.0,
            )

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and result["choices"]:
                    content = result["choices"][0].get("message", {}).get("content", "")
                    typer.echo("\n📤 Response:")
                    typer.echo(content)
                else:
                    typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(
                    f"Error: HTTP {response.status_code}: {response.text}", err=True
                )
        except httpx.ConnectError:
            typer.echo("Error: Could not connect to ModelAPI", err=True)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
    finally:
        cleanup()
