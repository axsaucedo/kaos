"""KAOS Agent memory command - get agent memory events."""

import json
import subprocess
import sys
import typer

from kaos_cli.utils.port_forward import PortForwardError, port_forward


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

    try:
        with port_forward(
            f"svc/agent-{name}",
            int(svc_port),
            namespace,
            "/health",
            local_port=port,
        ) as base_url:
            url = f"{base_url}/memory/events"
            if session_id:
                url += f"?session_id={session_id}"

            try:
                response = httpx.get(url, timeout=10.0)
                response.raise_for_status()
                memory = response.json()
            except httpx.HTTPError as exc:
                typer.echo(f"Error: Failed to get memory events: {exc}", err=True)
                raise typer.Exit(1)

            if output_json:
                typer.echo(json.dumps(memory, indent=2))
            else:
                events = memory.get("events", [])
                typer.echo(f"Memory Events: {len(events)} total")

                event_types: dict[str, int] = {}
                for event in events:
                    etype = event.get("event_type", "unknown")
                    event_types[etype] = event_types.get(etype, 0) + 1

                if event_types:
                    typer.echo("Event Types:")
                    for etype, count in sorted(event_types.items()):
                        typer.echo(f"  - {etype}: {count}")

                if events:
                    typer.echo("\nAll Events:")
                    for event in events:
                        etype = event.get("event_type", "unknown")
                        content = event.get("content", "")
                        if isinstance(content, dict):
                            content = json.dumps(content)
                        typer.echo(f"  [{etype}] {content}")
    except PortForwardError as exc:
        typer.echo(f"Error: Port-forward failed: {exc}", err=True)
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
