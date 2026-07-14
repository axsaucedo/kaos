"""OIDC login and local token caching."""

import base64
import json

import httpx
import typer

from kaos_cli.config import cache_session, load_config


def _token_claims(token: str) -> dict:
    """Decode unverified JWT claims for display; the gateway verifies the token."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, json.JSONDecodeError):
        return {}


def login_command(user: str, password: str | None = None) -> None:
    """Get a password-grant token from the configured OIDC issuer."""
    config = load_config()
    issuer = config["auth"].get("issuer", "").rstrip("/")
    client_id = config["auth"].get("client_id", "")
    if not issuer or not client_id:
        typer.echo("Error: configure auth.issuer and auth.client_id first", err=True)
        raise typer.Exit(1)
    password = password or typer.prompt("Password", hide_input=True)
    endpoint = issuer if issuer.endswith("/token") else f"{issuer}/protocol/openid-connect/token"
    try:
        response = httpx.post(
            endpoint,
            data={
                "grant_type": "password",
                "client_id": client_id,
                "username": user,
                "password": password,
                "scope": "openid profile email",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"Error: login failed: {exc}", err=True)
        raise typer.Exit(1)
    token = response.json().get("access_token")
    if not token:
        typer.echo("Error: login response did not include an access token", err=True)
        raise typer.Exit(1)
    groups = [str(group).lstrip("/") for group in _token_claims(token).get("groups", [])]
    cache_session(user, token, groups)
    typer.echo(f"✓ logged in as {user} — groups: {', '.join(groups) or 'none'}")
