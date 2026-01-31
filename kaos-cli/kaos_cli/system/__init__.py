"""KAOS system commands."""

import typer

from kaos_cli.system.install import install_command, uninstall_command
from kaos_cli.system.create_rbac import create_rbac_command
from kaos_cli.system.status import status_command
from kaos_cli.system.runtimes import runtimes_command

app = typer.Typer(
    help="System management commands for KAOS operator.",
    no_args_is_help=True,
)


@app.command(name="install")
def install(
    namespace: str = typer.Option(
        "kaos",
        "--namespace",
        "-n",
        help="Kubernetes namespace to install into.",
    ),
    release_name: str = typer.Option(
        "kaos-operator",
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
) -> None:
    """Install the KAOS operator using Helm."""
    install_command(
        namespace=namespace,
        release_name=release_name,
        version=version,
        set_values=list(set_values),
        wait=wait,
    )


@app.command(name="uninstall")
def uninstall(
    namespace: str = typer.Option(
        "kaos",
        "--namespace",
        "-n",
        help="Kubernetes namespace to uninstall from.",
    ),
    release_name: str = typer.Option(
        "kaos-operator",
        "--release-name",
        help="Helm release name.",
    ),
) -> None:
    """Uninstall the KAOS operator."""
    uninstall_command(namespace=namespace, release_name=release_name)


@app.command(name="create-rbac")
def create_rbac(
    name: str = typer.Argument(..., help="Name for the ServiceAccount and Role."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace for the ServiceAccount.",
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
        help="Kubernetes verbs to grant.",
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
) -> None:
    """Create RBAC resources for MCPServer Kubernetes runtime."""
    create_rbac_command(
        name=name,
        namespace=namespace,
        namespaces=list(namespaces),
        resources=list(resources),
        verbs=list(verbs),
        read_only=read_only,
        cluster_wide=cluster_wide,
    )


@app.command(name="status")
def status(
    namespace: str = typer.Option(
        "kaos",
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
        "kaos",
        "--namespace",
        "-n",
        help="Namespace where KAOS operator is installed.",
    ),
) -> None:
    """List available MCP runtimes."""
    runtimes_command(namespace=namespace)
