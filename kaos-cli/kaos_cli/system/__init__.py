"""KAOS system commands."""

import subprocess
import sys

import typer

from kaos_cli.system.install import install_command, uninstall_command
from kaos_cli.system.create_rbac import create_rbac_command
from kaos_cli.system.status import status_command
from kaos_cli.install import DEFAULT_RELEASE_NAME, MONITORING_BACKENDS
from kaos_cli.system.runtimes import runtimes_command

app = typer.Typer(
    help="System management commands for KAOS operator.",
    no_args_is_help=True,
)


@app.command(name="install")
def install(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Kubernetes namespace to install into.",
    ),
    release_name: str = typer.Option(
        DEFAULT_RELEASE_NAME,
        "--release-name",
        help="Helm release name.",
    ),
    version: str = typer.Option(
        None,
        "--version",
        help="Chart version to install. Defaults to latest.",
    ),
    set_values: list[str] = typer.Option(
        [],
        "--set",
        help="Set Helm values (can be used multiple times).",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Wait for pods to be ready before returning.",
    ),
    monitoring_enabled: str | None = typer.Option(
        None,
        "--monitoring-enabled",
        help=f"Install monitoring stack and enable telemetry. Options: {', '.join(MONITORING_BACKENDS)}.",
    ),
) -> None:
    """Install the KAOS operator using Helm."""
    # Default to signoz if flag provided without value
    if monitoring_enabled is not None and monitoring_enabled not in MONITORING_BACKENDS:
        typer.echo(
            f"Error: Invalid monitoring backend '{monitoring_enabled}'. Options: {', '.join(MONITORING_BACKENDS)}",
            err=True,
        )
        raise typer.Exit(1)
    install_command(
        namespace=namespace,
        release_name=release_name,
        version=version,
        set_values=list(set_values),
        wait=wait,
        monitoring_enabled=monitoring_enabled,
    )


@app.command(name="uninstall")
def uninstall(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Kubernetes namespace to uninstall from.",
    ),
    release_name: str = typer.Option(
        DEFAULT_RELEASE_NAME,
        "--release-name",
        help="Helm release name.",
    ),    monitoring_enabled: str | None = typer.Option(
        None,
        "--monitoring-enabled",
        help=f"Also uninstall monitoring stack. Options: {', '.join(MONITORING_BACKENDS)}.",
    ),
) -> None:
    """Uninstall the KAOS operator."""
    if monitoring_enabled is not None and monitoring_enabled not in MONITORING_BACKENDS:
        typer.echo(
            f"Error: Invalid monitoring backend '{monitoring_enabled}'. Options: {', '.join(MONITORING_BACKENDS)}",
            err=True,
        )
        raise typer.Exit(1)
    uninstall_command(
        namespace=namespace,
        release_name=release_name,
        monitoring_enabled=monitoring_enabled,
    )


@app.command(name="create-rbac")
def create_rbac(
    name: str = typer.Argument(..., help="Name for the ServiceAccount and Role."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace for the ServiceAccount. Uses current context if not specified.",
    ),
    namespaces: list[str] = typer.Option(
        [],
        "--namespaces",
        help="Additional namespaces for RoleBindings (can be used multiple times).",
    ),
    resources: list[str] = typer.Option(
        [],
        "--resources",
        help="Kubernetes resources to grant access to.",
    ),
    verbs: list[str] = typer.Option(
        [],
        "--verbs",
        help="Kubernetes verbs to grant (comma-separated or repeated).",
    ),
    read_only: bool = typer.Option(
        False,
        "--read-only",
        help="Grant only get/list/watch permissions.",
    ),
    cluster_wide: bool = typer.Option(
        False,
        "--cluster-wide",
        help="Create ClusterRole and ClusterRoleBinding instead of Role.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only print YAML without applying to cluster.",
    ),
) -> None:
    """Create RBAC resources for MCPServer Kubernetes runtime."""
    # Split comma-separated values for resources and verbs
    expanded_resources = []
    for r in resources:
        expanded_resources.extend(r.split(","))

    expanded_verbs = []
    for v in verbs:
        expanded_verbs.extend(v.split(","))

    create_rbac_command(
        name=name,
        namespace=namespace,
        namespaces=list(namespaces),
        resources=expanded_resources,
        verbs=expanded_verbs,
        read_only=read_only,
        cluster_wide=cluster_wide,
        dry_run=dry_run,
    )


@app.command(name="status")
def status(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Namespace where KAOS operator is installed.",
    ),
) -> None:
    """Show KAOS system status."""
    status_command(namespace=namespace)


@app.command(name="runtimes")
def runtimes(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Namespace where KAOS operator is installed.",
    ),
) -> None:
    """List available MCP runtimes."""
    runtimes_command(namespace=namespace)


@app.command(name="working-namespace")
def working_namespace(
    namespace: str = typer.Argument(..., help="Namespace to switch to."),
) -> None:
    """Set the working namespace for kubectl.

    Creates the namespace if it doesn't exist and switches kubectl context.
    """
    # Create namespace if it doesn't exist
    result = subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        typer.echo(f"✅ Created namespace '{namespace}'")
    elif "already exists" in result.stderr:
        typer.echo(f"📦 Namespace '{namespace}' already exists")
    else:
        typer.echo(f"Error: {result.stderr}", err=True)
        sys.exit(result.returncode)

    # Get current context
    result = subprocess.run(
        ["kubectl", "config", "current-context"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Error getting current context: {result.stderr}", err=True)
        sys.exit(result.returncode)
    current_context = result.stdout.strip()

    # Set namespace in current context
    result = subprocess.run(
        [
            "kubectl",
            "config",
            "set-context",
            current_context,
            "--namespace",
            namespace,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Error setting namespace: {result.stderr}", err=True)
        sys.exit(result.returncode)

    typer.echo(f"✅ Switched to namespace '{namespace}'")
