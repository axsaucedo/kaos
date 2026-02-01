"""KAOS ModelAPI commands."""

import typer

from kaos_cli.utils.crud import (
    list_resources,
    get_resource,
    logs_resource,
    delete_resource,
)
from kaos_cli.modelapi.deploy import deploy_from_yaml, deploy_modelapi
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
    list_resources("modelapi", namespace, output)


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
    get_resource("modelapi", name, namespace, output)


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
    logs_resource("modelapi", name, namespace, follow, tail)


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
    delete_resource("modelapi", name, namespace, force)


@app.command(name="deploy")
def deploy_modelapi_cmd(
    file: str = typer.Argument(None, help="Path to ModelAPI YAML file."),
    name: str = typer.Option(None, "--name", help="Name for the ModelAPI."),
    backend: str = typer.Option(
        "litellm", "--backend", "-b", help="Backend type (litellm, ollama)."
    ),
    model: str = typer.Option(None, "--model", "-m", help="Model name."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace to deploy to.",
    ),
) -> None:
    """Deploy a ModelAPI from YAML file or flags.

    Examples:
      kaos modelapi deploy config.yaml                      # Deploy from YAML file
      kaos modelapi deploy --name my-api --model gpt-4      # Deploy with flags
    """
    import sys

    if file:
        deploy_from_yaml(file=file, namespace=namespace)
    elif name and model:
        deploy_modelapi(
            name=name,
            backend=backend,
            model=model,
            namespace=namespace,
        )
    else:
        typer.echo("Error: Provide FILE, or --name and --model", err=True)
        sys.exit(1)


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
    invoke_command(
        name=name, namespace=namespace, message=message, model=model, port=port
    )
