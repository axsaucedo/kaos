"""PAIS CLI — run and init commands for Pydantic AI agents."""

import importlib
import importlib.util
import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="pais",
    help="Pydantic AI Server — run and manage custom agents.",
    no_args_is_help=True,
)


def _discover_agent(module):
    """Find a pydantic_ai.Agent instance in a module."""
    from pydantic_ai import Agent

    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, Agent):
            return obj
    return None


def _import_module_from_file(file_path: str):
    """Import a Python file as a module."""
    path = Path(file_path).resolve()
    # Auto-add .py extension if file doesn't exist but .py version does
    if not path.exists() and not path.suffix and path.with_suffix(".py").exists():
        path = path.with_suffix(".py")
    if not path.exists():
        typer.echo(f"Error: File '{file_path}' not found", err=True)
        raise typer.Exit(1)

    # Add parent directory to sys.path so imports work
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_agent_server(target: str, host: str, port: int, reload: bool):
    """Core logic for running an agent server from a file[:attribute] target."""
    # Parse file:attribute
    if ":" in target:
        file_part, attr = target.rsplit(":", 1)
    else:
        file_part = target
        attr = None

    # Default to agent.py
    if not file_part:
        file_part = "agent.py"

    module = _import_module_from_file(file_part)

    if attr:
        agent = getattr(module, attr, None)
        if agent is None:
            typer.echo(f"Error: '{attr}' not found in {file_part}", err=True)
            raise typer.Exit(1)
    else:
        agent = _discover_agent(module)
        if agent is None:
            typer.echo(f"Error: No pydantic_ai.Agent found in {file_part}", err=True)
            raise typer.Exit(1)

    typer.echo(f"🚀 Starting agent server from {file_part}")

    from pais import serve

    asgi_app = serve(agent)

    import uvicorn

    uvicorn.run(asgi_app, host=host, port=port, reload=reload)


@app.command(name="run")
def run(
    target: str = typer.Argument(
        "agent.py",
        help="Python file or file:attribute (default: agent.py).",
    ),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", "-r", help="Auto-reload on changes."),
) -> None:
    """Run a Pydantic AI agent server locally."""
    run_agent_server(target, host, port, reload)


@app.command(name="init")
def init(
    directory: str = typer.Argument(
        None, help="Directory to initialize. Defaults to current directory."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Initialize a new custom Pydantic AI agent project."""
    try:
        from kaos_cli.agent.init import init_command  # type: ignore[import-untyped]  # ty: ignore[unresolved-import]

        init_command(directory=directory, force=force)
    except ImportError:
        typer.echo(
            "Error: kaos-cli not installed. Install with: pip install pydantic-ai-server[cli]",
            err=True,
        )
        raise typer.Exit(1)


@app.command(name="version")
def version_cmd() -> None:
    """Show PAIS version."""
    from pais import __version__

    typer.echo(f"pais {__version__}")
