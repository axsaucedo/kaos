"""KAOS Agent memory command - get agent memory events."""

import json
import subprocess
import sys
import time
import signal
import typer


def memory_command(
    name: str,
    namespace: str | None,
    session_id: str | None,
    port: int,
    output_json: bool,
) -> None:
    """Get agent memory events via port-forward."""
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
        # Build URL with optional session_id filter
        url = f"http://localhost:{port}/memory/events"
        if session_id:
            url += f"?session_id={session_id}"

        # Retry logic for port-forward to be ready
        memory = None
        last_error = None
        for attempt in range(5):
            try:
                response = httpx.get(url, timeout=10.0)
                if response.status_code == 200:
                    memory = response.json()
                    break
                else:
                    last_error = f"HTTP {response.status_code}"
            except httpx.ConnectError as e:
                last_error = str(e)
                time.sleep(1)

        if memory is None:
            typer.echo(f"Error: Failed to get memory events: {last_error}", err=True)
            sys.exit(1)

        if output_json:
            typer.echo(json.dumps(memory, indent=2))
        else:
            # Pretty print memory events
            events = memory.get("events", [])
            typer.echo(f"Memory Events: {len(events)} total")
            
            # Group by event type
            event_types: dict[str, int] = {}
            for event in events:
                etype = event.get("event_type", "unknown")
                event_types[etype] = event_types.get(etype, 0) + 1
            
            if event_types:
                typer.echo("Event Types:")
                for etype, count in sorted(event_types.items()):
                    typer.echo(f"  - {etype}: {count}")
            
            # Show last few events
            if events:
                typer.echo("\nRecent Events:")
                for event in events[-5:]:
                    etype = event.get("event_type", "unknown")
                    content = event.get("content", "")
                    if isinstance(content, str) and len(content) > 60:
                        content = content[:60] + "..."
                    typer.echo(f"  [{etype}] {content}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        cleanup()
