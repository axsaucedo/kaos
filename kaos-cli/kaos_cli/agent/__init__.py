"""KAOS Agent commands."""

import typer

from kaos_cli.agent.crud import list_command, get_command, logs_command, delete_command, deploy_command
from kaos_cli.agent.invoke import invoke_command

app = typer.Typer(
    help="Agent management commands.",
    no_args_is_help=True,
)


@app.command(name="list")
def list_agents(
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
    """List Agent resources."""
    list_command(namespace=namespace, output=output)


@app.command(name="get")
def get_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
    ),
    output: str = typer.Option(
        "yaml",
        "--output",
        "-o",
        help="Output format (yaml, json, wide).",
    ),
) -> None:
    """Get a specific Agent resource."""
    get_command(name=name, namespace=namespace, output=output)


@app.command(name="logs")
def logs_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
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
    """View logs from an Agent pod."""
    logs_command(name=name, namespace=namespace, follow=follow, tail=tail)


@app.command(name="delete")
def delete_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Delete an Agent resource."""
    delete_command(name=name, namespace=namespace, force=force)


@app.command(name="deploy")
def deploy_agent(
    file: str = typer.Argument(..., help="Path to Agent YAML file."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to deploy to (overrides YAML metadata).",
    ),
) -> None:
    """Deploy an Agent from a YAML file."""
    deploy_command(file=file, namespace=namespace)


@app.command(name="invoke")
def invoke_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    message: str = typer.Option(..., "--message", "-m", help="Message to send to the agent."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
    ),
    port: int = typer.Option(
        9001,
        "--port",
        "-p",
        help="Local port for port-forwarding.",
    ),
    stream: bool = typer.Option(
        False,
        "--stream",
        "-s",
        help="Stream the response.",
    ),
) -> None:
    """Send a message to an Agent via port-forward."""
    invoke_command(name=name, namespace=namespace, message=message, port=port, stream=stream)
