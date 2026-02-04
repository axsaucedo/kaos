"""KAOS ModelAPI commands."""

import typer

from kaos_cli.utils.crud import (
    list_resources,
    get_resource,
    logs_resource,
    delete_resource,
)
from kaos_cli.modelapi.deploy import deploy_modelapi
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
        None,
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
        None,
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
        None,
        "--namespace",
        "-n",
        help="Namespace of the ModelAPI.",
    ),
) -> None:
    """Delete a ModelAPI resource."""
    delete_resource("modelapi", name, namespace)


@app.command(name="deploy")
def deploy_modelapi_cmd(
    name: str = typer.Argument(..., help="Name for the ModelAPI."),
    mode: str = typer.Option(
        "Proxy", "--mode", "-m", help="Mode: Proxy (LiteLLM) or Hosted (Ollama)."
    ),
    model: str = typer.Option(
        None, "--model", help="Model name (required for Hosted mode)."
    ),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to deploy to.",
    ),
    env_vars: list[str] = typer.Option(
        None, "--env", "-e", help="Environment variables (NAME=value format)."
    ),
    wait: bool = typer.Option(
        False, "--wait", help="Wait for deployment to be available."
    ),
    wait_timeout: int = typer.Option(
        120, "--wait-timeout", help="Timeout in seconds for --wait."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print YAML instead of deploying."
    ),
) -> None:
    """Deploy a ModelAPI.

    Examples:
      kaos modelapi deploy my-api                           # Deploy Proxy mode
      kaos modelapi deploy my-api --mode Hosted --model smollm2:135m  # Deploy Hosted
      kaos modelapi deploy my-api --wait                    # Wait for ready
      kaos modelapi deploy my-api --env LOG_LEVEL=DEBUG     # With env vars
    """
    deploy_modelapi(
        name=name,
        mode=mode,
        model=model,
        namespace=namespace,
        env_vars=env_vars,
        wait=wait,
        wait_timeout=wait_timeout,
        dry_run=dry_run,
    )


@app.command(name="invoke")
def invoke_modelapi(
    name: str = typer.Argument(..., help="Name of the ModelAPI."),
    message: str = typer.Option(..., "--message", "-m", help="Message to send."),
    model: str = typer.Option(..., "--model", help="Model name to use."),
    namespace: str = typer.Option(
        None,
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
