"""KAOS Agent commands."""

import typer

from kaos_cli.utils.crud import (
    list_resources,
    get_resource,
    logs_resource,
    delete_resource,
)
from kaos_cli.agent.deploy import deploy_agent
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
    list_resources("agent", namespace, output)


@app.command(name="get")
def get_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        None,
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
    get_resource("agent", name, namespace, output)


@app.command(name="logs")
def logs_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        None,
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
    logs_resource("agent", name, namespace, follow, tail)


@app.command(name="delete")
def delete_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        None,
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
    delete_resource("agent", name, namespace, force)


@app.command(name="deploy")
def deploy_agent_cmd(
    name: str = typer.Argument(..., help="Name for the Agent."),
    modelapi: str = typer.Option(..., "--modelapi", "-a", help="ModelAPI reference."),
    model: str = typer.Option(..., "--model", "-m", help="Model name to use."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to deploy to.",
    ),
    instructions: str = typer.Option(
        None, "--instructions", "-i", help="Agent instructions."
    ),
    mcp_servers: list[str] = typer.Option(None, "--mcp", help="MCP server references."),
    sub_agents: list[str] = typer.Option(
        None, "--sub-agent", help="Sub-agent references (agentNetwork.access)."
    ),
) -> None:
    """Deploy an Agent.

    Examples:
      kaos agent deploy my-agent --modelapi my-api --model smollm2:135m
      kaos agent deploy my-agent -a my-api -m gpt-4o --mcp calculator --sub-agent helper
    """
    deploy_agent(
        name=name,
        modelapi=modelapi,
        model=model,
        namespace=namespace,
        instructions=instructions,
        mcp_servers=mcp_servers,
        sub_agents=sub_agents,
    )


@app.command(name="invoke")
def invoke_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    message: str = typer.Option(
        ..., "--message", "-m", help="Message to send to the agent."
    ),
    namespace: str = typer.Option(
        None,
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
    invoke_command(
        name=name, namespace=namespace, message=message, port=port, stream=stream
    )
