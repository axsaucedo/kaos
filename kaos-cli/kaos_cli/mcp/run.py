"""KAOS MCP server run command - runs a FastMCP server locally."""

import importlib
import sys
from pathlib import Path

import typer


def _import_module_from_file(file_path: str):
    """Import a Python file as a module."""
    path = Path(file_path).resolve()
    if not path.exists():
        typer.echo(f"Error: File '{file_path}' not found", err=True)
        raise typer.Exit(1)

    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _discover_mcp_server(module):
    """Find a FastMCP server instance in a module."""
    try:
        from fastmcp import FastMCP

        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, FastMCP):
                return obj
    except ImportError:
        pass
    return None


def run_command(
    target: str,
    host: str,
    port: int,
    reload: bool,
) -> None:
    """Run a FastMCP server locally."""
    if ":" in target:
        file_part, attr = target.rsplit(":", 1)
    else:
        file_part = target
        attr = None

    if not file_part:
        file_part = "server.py"

    module = _import_module_from_file(file_part)

    if attr:
        server = getattr(module, attr, None)
        if server is None:
            typer.echo(f"Error: '{attr}' not found in {file_part}", err=True)
            raise typer.Exit(1)
    else:
        server = _discover_mcp_server(module)
        if server is None:
            typer.echo(
                f"Error: No FastMCP server found in {file_part}", err=True
            )
            raise typer.Exit(1)

    typer.echo(f"🚀 Starting MCP server from {file_part}")

    import uvicorn

    mcp_app = server.http_app(path="/mcp")
    uvicorn.run(mcp_app, host=host, port=port, reload=reload)
