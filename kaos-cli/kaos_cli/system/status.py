"""KAOS system status command."""

import subprocess
import sys
import typer


def status_command(namespace: str) -> None:
    """Show KAOS operator status."""
    typer.echo(f"KAOS System Status (namespace: {namespace})")
    typer.echo("=" * 50)

    # Check operator deployment
    typer.echo("\n📦 Operator:")
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployment",
                "-n",
                namespace,
                "-l",
                "app.kubernetes.io/name=kaos-operator",
                "-o",
                "wide",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            typer.echo(result.stdout)
        else:
            typer.echo("  Not found or not running")
    except FileNotFoundError:
        typer.echo("Error: kubectl not found", err=True)
        sys.exit(1)

    # Check CRDs
    typer.echo("\n📋 Custom Resource Definitions:")
    result = subprocess.run(
        ["kubectl", "get", "crd", "-o", "name"],
        capture_output=True,
        text=True,
    )
    crds = ["agents.kaos.tools", "mcpservers.kaos.tools", "modelapis.kaos.tools"]
    for crd in crds:
        if f"customresourcedefinitions.apiextensions.k8s.io/{crd}" in result.stdout:
            typer.echo(f"  ✅ {crd}")
        else:
            typer.echo(f"  ❌ {crd} (not installed)")

    # Count resources
    typer.echo("\n📊 Resources:")
    for kind, name in [
        ("Agent", "agents"),
        ("MCPServer", "mcpservers"),
        ("ModelAPI", "modelapis"),
    ]:
        result = subprocess.run(
            ["kubectl", "get", name, "--all-namespaces", "--no-headers"],
            capture_output=True,
            text=True,
        )
        count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        typer.echo(f"  {kind}: {count}")

    # Check Gateway
    typer.echo("\n🌐 Gateway:")
    result = subprocess.run(
        ["kubectl", "get", "gateway", "-n", "envoy-gateway-system", "-o", "wide"],
        capture_output=True,
        text=True,
    )
    if (
        result.returncode == 0
        and result.stdout.strip()
        and "No resources found" not in result.stdout
    ):
        typer.echo(result.stdout)
    else:
        typer.echo("  No gateway found in envoy-gateway-system")
