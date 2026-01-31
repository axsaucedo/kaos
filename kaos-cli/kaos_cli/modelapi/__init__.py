"""KAOS ModelAPI commands."""

import typer

from kaos_cli.modelapi.crud import list_command, get_command, logs_command, delete_command, deploy_command
from kaos_cli.modelapi.invoke import invoke_command

app = typer.Typer(
    help="ModelAPI management commands.",
    no_args_is_help=True,
)


@app.command(name="list")
def list_modelapis(
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to list from. Defaults to all namespaces.",
    ),
    output: str = typer.Option(
        "wide",
        "--output",
        "-o",
        help="Output format (wide, yaml, json, name).",
    ),
) -> None:
    """List ModelAPI resources."""
    list_command(namespace=namespace, output=output)


@app.command(name="get")
def get_modelapi(
    name: str = typer.Argument(..., help="Name of the ModelAPI."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the ModelAPI.",
    ),
    output: str = typer.Option(
        "yaml",
        "--output",
        "-o",
        help="Output format (yaml, json, wide).",
    ),
) -> None:
    """Get a specific ModelAPI resource."""
    get_command(name=name, namespace=namespace, output=output)


@app.command(name="logs")
def logs_modelapi(
    name: str = typer.Argument(..., help="Name of the ModelAPI."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the ModelAPI.",
    ),
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="Follow log output.",
    ),
    tail: int = typer.Option(
        None,
        "--tail",
        help="Number of lines to show from the end.",
    ),
) -> None:
    """View logs from a ModelAPI pod."""
    logs_command(name=name, namespace=namespace, follow=follow, tail=tail)


@app.command(name="delete")
def delete_modelapi(
    name: str = typer.Argument(..., help="Name of the ModelAPI."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the ModelAPI.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Delete a ModelAPI resource."""
    delete_command(name=name, namespace=namespace, force=force)


@app.command(name="deploy")
def deploy_modelapi(
    file: str = typer.Argument(..., help="Path to ModelAPI YAML file."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to deploy to (overrides YAML metadata).",
    ),
) -> None:
    """Deploy a ModelAPI from a YAML file."""
    deploy_command(file=file, namespace=namespace)


@app.command(name="invoke")
def invoke_modelapi(
    name: str = typer.Argument(..., help="Name of the ModelAPI."),
    message: str = typer.Option(..., "--message", "-m", help="Message to send."),
    model: str = typer.Option(..., "--model", help="Model name to use."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the ModelAPI.",
    ),
    port: int = typer.Option(
        9002,
        "--port",
        "-p",
        help="Local port for port-forwarding.",
    ),
) -> None:
    """Send a chat completion request to a ModelAPI via port-forward."""
    invoke_command(name=name, namespace=namespace, message=message, model=model, port=port)
