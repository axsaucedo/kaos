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
        "Proxy", "--mode", help="Mode: Proxy (LiteLLM) or Hosted (Ollama)."
    ),
    models: list[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model name(s). For Proxy: list of models. For Hosted: single model.",
    ),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to deploy to.",
    ),
    provider: str = typer.Option(
        None, "--provider", help="LiteLLM provider prefix (e.g., openai, anthropic)."
    ),
    base_url: str = typer.Option(None, "--base-url", help="Backend LLM API base URL."),
    api_secret: str = typer.Option(
        None,
        "--api-secret",
        help="API key secret (secretname:key format, or prompts for key).",
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
      kaos modelapi deploy my-api                           # Deploy Proxy mode with wildcard
      kaos modelapi deploy my-api -m gpt-4o -m gpt-3.5      # Proxy with specific models
      kaos modelapi deploy my-api --mode Hosted -m smollm2:135m  # Hosted mode
      kaos modelapi deploy my-api --provider openai --api-secret mysecret:key
      kaos modelapi deploy my-api --provider nebius --base-url https://api.nebius.ai/v1
      kaos modelapi deploy my-api --api-secret prompt       # Prompts for API key
    """
    deploy_modelapi(
        name=name,
        mode=mode,
        models=models,
        namespace=namespace,
        provider=provider,
        base_url=base_url,
        api_secret=api_secret,
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
