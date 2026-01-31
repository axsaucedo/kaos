"""KAOS MCP server commands."""

import typer

from kaos_cli.mcp.crud import list_command, get_command, logs_command, delete_command, deploy_command
from kaos_cli.mcp.invoke import invoke_command
from kaos_cli.mcp.init import init_command
from kaos_cli.mcp.build import build_command

app = typer.Typer(
    help="MCP server management commands.",
    no_args_is_help=True,
)


@app.command(name="init")
def init_mcp(
    directory: str = typer.Argument(
        None,
        help="Directory to initialize. Defaults to current directory.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing files.",
    ),
) -> None:
    """Initialize a new FastMCP server project."""
    init_command(directory=directory, force=force)


@app.command(name="build")
def build_mcp(
    name: str = typer.Option(..., "--name", "-n", help="Name for the image."),
    tag: str = typer.Option("latest", "--tag", "-t", help="Tag for the image."),
    directory: str = typer.Option(".", "--dir", "-d", help="Source directory."),
    entry_point: str = typer.Option("server.py", "--entry", "-e", help="Entry point file."),
    use_fastmcp_run: bool = typer.Option(False, "--fastmcp-run", help="Use 'fastmcp run' command."),
    kind_load: bool = typer.Option(False, "--kind-load", help="Load image to KIND cluster."),
    create_dockerfile: bool = typer.Option(False, "--create-dockerfile", help="Create/overwrite Dockerfile."),
    platform: str = typer.Option(None, "--platform", help="Docker platform (e.g., linux/amd64)."),
) -> None:
    """Build a Docker image from a FastMCP server."""
    build_command(
        name=name,
        tag=tag,
        directory=directory,
        entry_point=entry_point,
        use_fastmcp_run=use_fastmcp_run,
        kind_load=kind_load,
        create_dockerfile=create_dockerfile,
        platform=platform,
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


@app.command(name="invoke")
def invoke_mcpserver(
    name: str = typer.Argument(..., help="Name of the MCPServer."),
    tool: str = typer.Option(..., "--tool", "-t", help="Name of the MCP tool to invoke."),
    args: str = typer.Option(
        None,
        "--args",
        "-a",
        help="JSON arguments for the tool.",
    ),
    namespace: str = typer.Option(
        "default",
        "--namespace",
        "-n",
        help="Namespace of the MCPServer.",
    ),
    port: int = typer.Option(
        9000,
        "--port",
        "-p",
        help="Local port for port-forwarding.",
    ),
) -> None:
    """Invoke an MCP tool via port-forward."""
    invoke_command(name=name, namespace=namespace, tool=tool, args=args, port=port)
