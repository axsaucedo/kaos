"""KAOS MCP server commands."""

import typer

from kaos_cli.mcp.crud import list_command, get_command, logs_command, delete_command, deploy_command

app = typer.Typer(
    help="MCP server management commands.",
    no_args_is_help=True,
)


@app.command(name="list")
def list_mcpservers(
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
    """List MCPServer resources."""
    list_command(namespace=namespace, output=output)


@app.command(name="get")
def get_mcpserver(
    name: str = typer.Argument(..., help="Name of the MCPServer."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the MCPServer.",
    ),
    output: str = typer.Option(
        "yaml",
        "--output",
        "-o",
        help="Output format (yaml, json, wide).",
    ),
) -> None:
    """Get a specific MCPServer resource."""
    get_command(name=name, namespace=namespace, output=output)


@app.command(name="logs")
def logs_mcpserver(
    name: str = typer.Argument(..., help="Name of the MCPServer."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the MCPServer.",
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
    """View logs from an MCPServer pod."""
    logs_command(name=name, namespace=namespace, follow=follow, tail=tail)


@app.command(name="delete")
def delete_mcpserver(
    name: str = typer.Argument(..., help="Name of the MCPServer."),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the MCPServer.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Delete an MCPServer resource."""
    delete_command(name=name, namespace=namespace, force=force)


@app.command(name="deploy")
def deploy_mcpserver(
    file: str = typer.Argument(..., help="Path to MCPServer YAML file."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace to deploy to (overrides YAML metadata).",
    ),
) -> None:
    """Deploy an MCPServer from a YAML file."""
    deploy_command(file=file, namespace=namespace)
