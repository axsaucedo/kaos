"""KAOS Agent status command - get agent card information."""

import json
import subprocess
import sys
import time
import signal
import typer


def status_command(
    name: str,
    namespace: str | None,
    port: int,
    output_json: bool,
) -> None:
    """Get agent status/card via port-forward."""
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
        # Retry logic for port-forward to be ready
        card = None
        last_error = None
        for attempt in range(5):
            try:
                response = httpx.get(
                    f"http://localhost:{port}/.well-known/agent.json",
                    timeout=10.0,
                )
                if response.status_code == 200:
                    card = response.json()
                    break
                else:
                    last_error = f"HTTP {response.status_code}"
            except httpx.ConnectError as e:
                last_error = str(e)
                time.sleep(1)

        if card is None:
            typer.echo(f"Error: Failed to get agent card: {last_error}", err=True)
            sys.exit(1)

        if output_json:
            typer.echo(json.dumps(card, indent=2))
        else:
            # Pretty print status
            typer.echo(f"Agent: {card.get('name', name)}")
            typer.echo(f"Version: {card.get('version', 'unknown')}")
            
            capabilities = card.get("capabilities", {})
            if isinstance(capabilities, dict):
                enabled = [k for k, v in capabilities.items() if v]
                typer.echo(f"Capabilities: {', '.join(enabled) if enabled else 'none'}")
            else:
                typer.echo(f"Capabilities: {', '.join(capabilities) if capabilities else 'none'}")
            
            skills = card.get("skills", [])
            typer.echo(f"Skills: {len(skills)} discovered")
            for skill in skills[:10]:  # Show first 10
                skill_name = skill.get("name", "unknown")
                typer.echo(f"  - {skill_name}")
            if len(skills) > 10:
                typer.echo(f"  ... and {len(skills) - 10} more")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        cleanup()
