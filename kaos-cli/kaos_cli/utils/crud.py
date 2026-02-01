"""Shared CRUD utilities for KAOS CLI resource commands."""

import os
import subprocess
import sys
from typing import Literal

import typer


ResourceType = Literal["mcpserver", "agent", "modelapi"]

RESOURCE_PLURALS = {
    "mcpserver": "mcpservers",
    "agent": "agents",
    "modelapi": "modelapis",
}

RESOURCE_LABELS = {
    "mcpserver": "mcpserver",
    "agent": "agent",
    "modelapi": "modelapi",
}


def run_kubectl(
    args: list[str], exit_on_error: bool = True
) -> subprocess.CompletedProcess:
    """Run kubectl command."""
    cmd = ["kubectl"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and exit_on_error:
        typer.echo(result.stderr or result.stdout, err=True)
        sys.exit(result.returncode)
    return result


def list_resources(
    resource_type: ResourceType, namespace: str | None, output: str
) -> None:
    """List resources of a given type."""
    plural = RESOURCE_PLURALS[resource_type]
    args = ["get", plural]

    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")

    args.extend(["-o", output])

    result = run_kubectl(args)
    typer.echo(result.stdout)


def get_resource(
    resource_type: ResourceType, name: str, namespace: str, output: str
) -> None:
    """Get a specific resource."""
    args = ["get", resource_type, name, "-n", namespace, "-o", output]
    result = run_kubectl(args)
    typer.echo(result.stdout)


def logs_resource(
    resource_type: ResourceType,
    name: str,
    namespace: str,
    follow: bool,
    tail: int | None,
) -> None:
    """View logs from a resource pod."""
    label = RESOURCE_LABELS[resource_type]
    args = ["logs", "-l", f"{label}={name}", "-n", namespace]

    if follow:
        args.append("-f")

    if tail:
        args.extend(["--tail", str(tail)])

    if follow:
        os.execvp("kubectl", ["kubectl"] + args)
    else:
        result = run_kubectl(args)
        typer.echo(result.stdout)


def delete_resource(
    resource_type: ResourceType, name: str, namespace: str, force: bool
) -> None:
    """Delete a resource."""
    display_name = resource_type.capitalize()
    if not force:
        confirm = typer.confirm(
            f"Delete {display_name} '{name}' in namespace '{namespace}'?"
        )
        if not confirm:
            typer.echo("Cancelled.")
            return

    args = ["delete", resource_type, name, "-n", namespace]
    result = run_kubectl(args)
    typer.echo(result.stdout)


def deploy_from_file(file: str, namespace: str | None) -> None:
    """Deploy a resource from YAML file."""
    args = ["apply", "-f", file]

    if namespace:
        args.extend(["-n", namespace])

    result = run_kubectl(args)
    typer.echo(result.stdout)
