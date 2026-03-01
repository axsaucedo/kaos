"""KAOS Agent run command - runs a custom agent server locally."""

import typer


def run_command(
    target: str,
    host: str,
    port: int,
    reload: bool,
) -> None:
    """Run a Pydantic AI agent server locally.

    Target format: module:object (no .py extension).
    Converts to file.py:object for the pais runner.
    """
    # Convert module:object to file.py[:object] for pais runner
    if ":" in target:
        module_part, attr = target.rsplit(":", 1)
        file_target = f"{module_part}.py:{attr}"
    else:
        file_target = f"{target}.py"

    from pais.cli import run_agent_server

    run_agent_server(file_target, host, port, reload)
