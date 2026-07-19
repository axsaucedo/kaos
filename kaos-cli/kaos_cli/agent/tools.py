"""Inspect the tool definitions exposed by a deployed Agent."""

import json
import subprocess

import httpx
import typer

from kaos_cli.utils.port_forward import PortForwardError, port_forward


def tools_command(name: str, namespace: str | None, output_json: bool) -> None:
    """Fetch and print an Agent's model-facing tool definitions."""
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
        raise typer.Exit(1)

    try:
        with port_forward(
            f"svc/agent-{name}",
            int(result.stdout.strip() or "8000"),
            namespace,
            "/health",
        ) as base_url:
            response = httpx.get(f"{base_url}/tools", timeout=30.0)
            response.raise_for_status()
            data = response.json()
    except (PortForwardError, httpx.HTTPError, json.JSONDecodeError) as exc:
        typer.echo(f"Error: Could not list Agent tools: {exc}", err=True)
        raise typer.Exit(1)

    if output_json:
        typer.echo(json.dumps(data, indent=2))
        return

    tools = data.get("tools", [])
    typer.echo(f"Tools for {data.get('agent', name)}: {len(tools)}")
    for tool in tools:
        typer.echo(f"\n{tool.get('name', '')}")
        if tool.get("description"):
            typer.echo(f"  {tool['description']}")
        schema = json.dumps(tool.get("parameters_json_schema", {}), indent=2)
        typer.echo("  Schema:")
        typer.echo("\n".join(f"    {line}" for line in schema.splitlines()))
