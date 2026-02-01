"""KAOS system runtimes command."""

import subprocess
import sys
import typer
import yaml


def runtimes_command(namespace: str) -> None:
    """List available MCP runtimes from ConfigMap."""
    typer.echo(
        f"Available MCP Runtimes (from kaos-mcp-runtimes ConfigMap in {namespace})"
    )
    typer.echo("=" * 60)

    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "configmap",
                "kaos-mcp-runtimes",
                "-n",
                namespace,
                "-o",
                "jsonpath={.data.runtimes\\.yaml}",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            typer.echo(f"\n❌ ConfigMap not found in namespace {namespace}")
            typer.echo("   Is KAOS installed? Run: kaos system install")
            return

        if not result.stdout.strip():
            typer.echo("\n⚠️ ConfigMap exists but has no runtimes.yaml data")
            return

        # Parse the YAML
        try:
            data = yaml.safe_load(result.stdout)
        except yaml.YAMLError as e:
            typer.echo(f"Error parsing runtimes.yaml: {e}", err=True)
            return

        runtimes = data.get("runtimes", {})
        if not runtimes:
            typer.echo("\nNo runtimes defined")
            return

        typer.echo("")
        for name, config in runtimes.items():
            transport = config.get("transport", "unknown")
            runtime_type = config.get("type", "unknown")
            image = config.get("image", "N/A")
            description = config.get("description", "")

            typer.echo(f"📦 {name}")
            typer.echo(f"   Type: {runtime_type} | Transport: {transport}")
            typer.echo(f"   Image: {image}")
            if description:
                typer.echo(f"   {description}")
            typer.echo("")

        typer.echo(f"Total: {len(runtimes)} runtime(s)")

    except FileNotFoundError:
        typer.echo("Error: kubectl not found", err=True)
        sys.exit(1)
