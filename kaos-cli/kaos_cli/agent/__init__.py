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
from kaos_cli.agent.status import status_command
from kaos_cli.agent.memory import memory_command
from kaos_cli.agent.init import init_command
from kaos_cli.agent.build import build_command
from kaos_cli.agent.run import run_command

app = typer.Typer(
    help="Agent management commands.",
    no_args_is_help=True,
)


@app.command(name="init")
def init_agent(
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
    """Initialize a new custom Pydantic AI agent project."""
    init_command(directory=directory, force=force)


@app.command(name="build")
def build_agent(
    name: str = typer.Option(..., "--name", "-n", help="Name for the image."),
    tag: str = typer.Option("latest", "--tag", "-t", help="Tag for the image."),
    directory: str = typer.Option(".", "--dir", "-d", help="Source directory."),
    entry_point: str = typer.Option(
        "server.py", "--entry", "-e", help="Entry point file."
    ),
    kind_load: bool = typer.Option(
        False, "--kind-load", help="Load image to KIND cluster."
    ),
    create_dockerfile: bool = typer.Option(
        False, "--create-dockerfile", help="Create/overwrite Dockerfile."
    ),
    platform: str = typer.Option(
        None, "--platform", help="Docker platform (e.g., linux/amd64)."
    ),
    base_image: str = typer.Option(
        None,
        "--base-image",
        help="Base Docker image (default: ghcr.io/axsaucedo/kaos-agent:latest).",
    ),
) -> None:
    """Build a Docker image from a custom Pydantic AI agent."""
    build_command(
        name=name,
        tag=tag,
        directory=directory,
        entry_point=entry_point,
        kind_load=kind_load,
        create_dockerfile=create_dockerfile,
        platform=platform,
        base_image=base_image,
    )


@app.command(name="run")
def run_agent(
    target: str = typer.Argument(
        "server.py",
        help="Python file or file:attribute (default: server.py).",
    ),
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", "-r", help="Auto-reload on changes."),
) -> None:
    """Run a Pydantic AI agent server locally."""
    run_command(target=target, host=host, port=port, reload=reload)


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
) -> None:
    """Delete an Agent resource."""
    delete_resource("agent", name, namespace)


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
    description: str = typer.Option(
        None, "--description", "-d", help="Agent description."
    ),
    instructions: str = typer.Option(
        None, "--instructions", "-i", help="Agent instructions."
    ),
    mcp_servers: list[str] = typer.Option(None, "--mcp", help="MCP server references."),
    sub_agents: list[str] = typer.Option(
        None, "--sub-agent", help="Sub-agent references (agentNetwork.access)."
    ),
    mock_responses: list[str] = typer.Option(
        None,
        "--mock-response",
        help="Mock responses for testing (DEBUG_MOCK_RESPONSES).",
    ),
    expose: bool = typer.Option(
        False, "--expose", help="Expose agent via Gateway (agentNetwork.expose)."
    ),
    otel_endpoint: str = typer.Option(
        None, "--otel-endpoint", help="OpenTelemetry endpoint (enables telemetry)."
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
    """Deploy an Agent.

    Examples:
      kaos agent deploy my-agent --modelapi my-api --model smollm2:135m
      kaos agent deploy my-agent -a my-api -m gpt-4o --mcp calculator --sub-agent helper
      kaos agent deploy my-agent -a my-api -m test --mock-response "Hello!" --expose
      kaos agent deploy my-agent -a my-api -m gpt-4o --otel-endpoint http://otel:4317
      kaos agent deploy my-agent -a my-api -m gpt-4o --description "My helpful agent"
    """
    deploy_agent(
        name=name,
        modelapi=modelapi,
        model=model,
        namespace=namespace,
        description=description,
        instructions=instructions,
        mcp_servers=mcp_servers,
        sub_agents=sub_agents,
        mock_responses=mock_responses,
        expose=expose,
        otel_endpoint=otel_endpoint,
        env_vars=env_vars,
        wait=wait,
        wait_timeout=wait_timeout,
        dry_run=dry_run,
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


@app.command(name="status")
def status_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
    ),
    port: int = typer.Option(
        9002,
        "--port",
        "-p",
        help="Local port for port-forwarding.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output in JSON format.",
    ),
) -> None:
    """Get agent status and capabilities via agent card.
    
    Examples:
      kaos agent status my-agent
      kaos agent status my-agent --json
      kaos agent status my-agent -n my-namespace
    """
    status_command(name=name, namespace=namespace, port=port, output_json=output_json)


@app.command(name="memory")
def memory_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
    ),
    session_id: str = typer.Option(
        None,
        "--session-id",
        "-s",
        help="Filter events by session ID.",
    ),
    port: int = typer.Option(
        9003,
        "--port",
        "-p",
        help="Local port for port-forwarding.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output in JSON format.",
    ),
) -> None:
    """Get agent memory events.
    
    Examples:
      kaos agent memory my-agent
      kaos agent memory my-agent --json
      kaos agent memory my-agent --session-id abc123
    """
    memory_command(
        name=name,
        namespace=namespace,
        session_id=session_id,
        port=port,
        output_json=output_json,
    )
