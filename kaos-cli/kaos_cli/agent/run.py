"""KAOS Agent run command - runs a custom agent server locally."""

import typer


def run_command(
    target: str,
    host: str,
    port: int,
    reload: bool,
) -> None:
    """Run a Pydantic AI agent server locally."""
    from pais.cli import run_agent_server

    run_agent_server(target, host, port, reload)
