"""KAOS authentication and access grant commands."""

import typer

from kaos_cli.auth.consent import consent_command
from kaos_cli.auth.grant import (
    create_grant_command,
    delete_grant_command,
    list_grants_command,
)
from kaos_cli.auth.login import login_command


app = typer.Typer(help="Log in and manage KAOS authorization.", no_args_is_help=True)
grant_app = typer.Typer(help="Create and manage AccessGrant resources.", no_args_is_help=True)
app.add_typer(grant_app, name="grant")


@app.command(name="login")
def login(
    user: str = typer.Argument(..., help="User name to log in as."),
    password: str | None = typer.Option(
        None,
        "--password",
        hidden=True,
        help="OIDC password (prompts when omitted).",
    ),
) -> None:
    """Log in through the configured OIDC service and cache the token."""
    login_command(user, password)


@grant_app.command(name="create")
def grant_create(
    group: str | None = typer.Option(None, "--group", help="Group receiving access."),
    user: str | None = typer.Option(None, "--user", help="User receiving access."),
    agent: str | None = typer.Option(None, "--agent", help="Agent receiving access."),
    resource: list[str] = typer.Option(..., "--resource", help="Resource kind/name; comma-separated or repeatable."),
    name: str | None = typer.Option(None, "--name", help="AccessGrant name (generated when omitted)."),
    namespace: str | None = typer.Option(None, "--namespace", "-n", help="Target namespace."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print YAML instead of applying it."),
) -> None:
    """Create an AccessGrant for a user, group, or agent."""
    create_grant_command(group, user, agent, resource, name, namespace, dry_run)


@grant_app.command(name="list")
def grant_list(
    namespace: str | None = typer.Option(None, "--namespace", "-n", help="Target namespace."),
) -> None:
    """List AccessGrant resources."""
    list_grants_command(namespace)


@grant_app.command(name="delete")
def grant_delete(
    name: str = typer.Argument(..., help="AccessGrant name."),
    namespace: str | None = typer.Option(None, "--namespace", "-n", help="Target namespace."),
) -> None:
    """Delete an AccessGrant."""
    delete_grant_command(name, namespace)


@app.command(name="connect")
def connect(
    service: str = typer.Argument(..., help="Delegated outside service."),
    user: str = typer.Option(..., "--user", help="User granting consent."),
) -> None:
    """Connect a user's delegated outside service."""
    consent_command(service, user, disconnect=False)


@app.command(name="disconnect")
def disconnect(
    service: str = typer.Argument(..., help="Delegated outside service."),
    user: str = typer.Option(..., "--user", help="User revoking consent."),
) -> None:
    """Disconnect a user's delegated outside service."""
    consent_command(service, user, disconnect=True)
