"""KAOS system commands."""

import typer

from kaos_cli.system.install import install_command, uninstall_command

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
