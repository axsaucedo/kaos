"""Delegated-access consent command placeholders."""

import typer


def consent_command(service: str, user: str, disconnect: bool = False) -> None:
    """Validate consent arguments until the broker exposes a stable CLI endpoint."""
    action = "disconnect" if disconnect else "connect"
    typer.echo(
        f"TODO: cannot {action} {service} for {user}: "
        "the token-exchange broker consent endpoint is not configured"
    )
    raise typer.Exit(1)
