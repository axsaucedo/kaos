"""KAOS CLI main entry point."""

from typing import List

import typer

from kaos_cli.install import (
    DEFAULT_NAMESPACE,
    DEFAULT_RELEASE_NAME,
    install_command,
    uninstall_command,
)
from kaos_cli.ui import ui_command

# Disable shell completion message
app = typer.Typer(
    add_completion=False,
    help="KAOS - K8s Agent Orchestration System CLI",
    no_args_is_help=True,
)


@app.command(name="ui")
def ui(
    k8s_url: str = typer.Option(
        None,
        "--k8s-url",
        help="Kubernetes API server URL. If not provided, uses kubeconfig.",
    ),
    expose_port: int = typer.Option(
        8080,
        "--expose-port",
        help="Port to expose the CORS proxy on.",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Don't automatically open the browser.",
    ),
) -> None:
    """Start a CORS-enabled proxy and open the KAOS UI."""
    ui_command(k8s_url=k8s_url, expose_port=expose_port, no_browser=no_browser)


@app.command(name="install")
def install(
    namespace: str = typer.Option(
        DEFAULT_NAMESPACE,
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
    set_values: List[str] = typer.Option(
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
        DEFAULT_NAMESPACE,
        "--namespace",
        "-n",
        help="Kubernetes namespace to uninstall from.",
    ),
    release_name: str = typer.Option(
        DEFAULT_RELEASE_NAME,
        "--release-name",
        help="Helm release name.",
    ),
) -> None:
    """Uninstall the KAOS operator."""
    uninstall_command(namespace=namespace, release_name=release_name)


@app.command(name="version")
def version() -> None:
    """Show the KAOS CLI version."""
    from kaos_cli import __version__

    typer.echo(f"kaos-cli {__version__}")


if __name__ == "__main__":
    app()
