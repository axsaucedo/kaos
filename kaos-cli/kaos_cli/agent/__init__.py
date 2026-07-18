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
from kaos_cli.agent.tools import tools_command
from kaos_cli.agent.init import init_command
from kaos_cli.agent.build import build_command
from kaos_cli.agent.run import run_command
from kaos_cli.agent.a2a import app as a2a_app

app = typer.Typer(
    help="Agent management commands.",
    no_args_is_help=True,
)
app.add_typer(a2a_app, name="a2a")


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
    target: str = typer.Argument(
        "agent:agent",
        help="Module:object target (default: agent:agent). No .py extension.",
    ),
    image: str = typer.Option(..., "--image", "-i", help="Image name with tag (e.g. my-agent:latest)."),
    directory: str = typer.Option(".", "--dir", "-d", help="Source directory."),
    kind_load: bool = typer.Option(
        False, "--kind-load", help="Load image to KIND cluster."
    ),
    push: bool = typer.Option(
        False, "--push", help="Push image to registry after build."
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
        help="Base Docker image (default: axsauze/kaos-agent:<version>).",
    ),
) -> None:
    """Build a Docker image from a custom Pydantic AI agent.

    Examples:
      kaos agent build --image my-agent:latest
      kaos agent build agent:my_bot --image my-agent:v2 --kind-load
      kaos agent build --image reg.io/agent:v1 --push
    """
    build_command(
        target=target,
        image=image,
        directory=directory,
        kind_load=kind_load,
        push=push,
        create_dockerfile=create_dockerfile,
        platform=platform,
        base_image=base_image,
    )


@app.command(name="run")
def run_agent(
    target: str = typer.Argument(
        "agent:agent",
        help="Module:object target (default: agent:agent). No .py extension.",
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
    image: str = typer.Option(
        None, "--image", "-i", help="Custom container image (e.g. my-agent:latest)."
    ),
    build: str = typer.Option(
        None,
        "--build",
        help="Build image before deploy. Optional target (default: agent:agent).",
    ),
    kind_load: bool = typer.Option(
        False, "--kind-load", help="Load image to KIND cluster (requires --build)."
    ),
    push: bool = typer.Option(
        False, "--push", help="Push image to registry (requires --build)."
    ),
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
        None, "--instructions", help="Agent instructions."
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
    autonomous: str = typer.Option(
        None, "--autonomous", help="Enable autonomous mode with the given goal."
    ),
    auto_max_iter_runtime: int = typer.Option(
        None,
        "--auto-max-iter-runtime",
        help="Max per-iteration runtime in seconds for continuous mode (0=unlimited).",
    ),
    auto_interval: float = typer.Option(
        None, "--auto-interval", help="Seconds between autonomous iterations."
    ),
    task_max_iterations: int = typer.Option(
        None, "--task-max-iterations", help="Max iterations for A2A async tasks (0=unlimited)."
    ),
    task_max_runtime: int = typer.Option(
        None, "--task-max-runtime", help="Max runtime in seconds for A2A async tasks (0=unlimited)."
    ),
    task_max_tool_calls: int = typer.Option(
        None, "--task-max-tool-calls", help="Max cumulative tool calls for A2A async tasks (0=unlimited)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print YAML instead of deploying."
    ),
) -> None:
    """Deploy an Agent.

    Examples:
      kaos agent deploy my-agent --modelapi my-api --model smollm2:135m
      kaos agent deploy my-agent --image my-agent:latest --modelapi my-api --model gpt-4o
      kaos agent deploy my-agent --image my-agent:latest --build --kind-load --modelapi my-api --model gpt-4o
      kaos agent deploy my-agent --image my-agent:latest --build agent:bot --modelapi my-api --model gpt-4o
      kaos agent deploy my-agent -a my-api -m gpt-4o --sub-agent helper --expose
      kaos agent deploy my-agent -a my-api -m gpt-4o --autonomous "Monitor system health"
    """
    import sys

    # Validate --build requires --image
    if build is not None and not image:
        typer.echo("Error: --build requires --image to be set", err=True)
        sys.exit(1)

    # Run build if requested
    if build is not None:
        build_target = build if build else "agent:agent"
        typer.echo(f"🔨 Building {build_target} → {image}...")
        build_command(
            target=build_target,
            image=image,
            directory=".",
            kind_load=kind_load,
            push=push,
            create_dockerfile=False,
            platform=None,
            base_image=None,
        )

    deploy_agent(
        name=name,
        modelapi=modelapi,
        model=model,
        image=image,
        namespace=namespace,
        description=description,
        instructions=instructions,
        mcp_servers=mcp_servers,
        sub_agents=sub_agents,
        mock_responses=mock_responses,
        expose=expose,
        otel_endpoint=otel_endpoint,
        env_vars=env_vars,
        autonomous=autonomous,
        auto_max_iter_runtime=auto_max_iter_runtime,
        auto_interval=auto_interval,
        task_max_iterations=task_max_iterations,
        task_max_runtime=task_max_runtime,
        task_max_tool_calls=task_max_tool_calls,
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


@app.command(name="tools")
def tools_agent(
    name: str = typer.Argument(..., help="Name of the Agent."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace of the Agent.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output in JSON format.",
    ),
) -> None:
    """Show the tool definitions presented to the model."""
    tools_command(name=name, namespace=namespace, output_json=output_json)
