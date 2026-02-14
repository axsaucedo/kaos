"""KAOS CLI main entry point."""

from typing import Optional

import typer

from kaos_cli.ui import ui_command
from kaos_cli.install import MONITORING_BACKENDS
from kaos_cli.system import app as system_app
from kaos_cli.mcp import app as mcp_app
from kaos_cli.agent import app as agent_app
from kaos_cli.modelapi import app as modelapi_app
from kaos_cli.samples import app as samples_app

# Disable shell completion message
app = typer.Typer(
    add_completion=False,
    help="KAOS - K8s Agent Orchestration System CLI",
    no_args_is_help=True,
)

# Add subcommands
app.add_typer(system_app, name="system")
app.add_typer(mcp_app, name="mcp")
app.add_typer(agent_app, name="agent")
app.add_typer(modelapi_app, name="modelapi")
app.add_typer(samples_app, name="samples")


@app.command(name="ui")
def ui(
    k8s_url: str = typer.Option(
        None,
        "--k8s-url",
        help="Kubernetes API server URL. If not provided, uses kubeconfig.",
    ),
    expose_port: int = typer.Option(
        8010,
        "--expose-port",
        help="Port to expose the CORS proxy on.",
    ),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Initial namespace to display in the UI.",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Don't automatically open the browser.",
    ),
    version: str = typer.Option(
        None,
        "--version",
        "-v",
        help="UI version to use (e.g., 'dev', 'v0.1.3'). Defaults to CLI version.",
    ),
    monitoring_enabled: Optional[str] = typer.Option(
        None,
        "--monitoring-enabled",
        help=f"Enable monitoring UI port-forward. Options: {', '.join(MONITORING_BACKENDS)}.",
    ),
    monitoring_namespace: str = typer.Option(
        "monitoring",
        "--monitoring-namespace",
        help="Namespace where monitoring is installed.",
    ),
) -> None:
    """Start a CORS-enabled proxy and open the KAOS UI."""
    if monitoring_enabled is not None and monitoring_enabled not in MONITORING_BACKENDS:
        typer.echo(
            f"Error: Invalid monitoring backend '{monitoring_enabled}'. Options: {', '.join(MONITORING_BACKENDS)}",
            err=True,
        )
        raise typer.Exit(1)
    ui_command(
        k8s_url=k8s_url,
        expose_port=expose_port,
        namespace=namespace,
        no_browser=no_browser,
        version=version,
        monitoring_enabled=monitoring_enabled,
        monitoring_namespace=monitoring_namespace,
    )


@app.command(name="version")
def version() -> None:
    """Show the KAOS CLI version."""
    from kaos_cli import __version__

    typer.echo(f"kaos-cli {__version__}")


if __name__ == "__main__":
    app()
