"""Connect and disconnect delegated third-party OAuth2 sessions."""

import re
import time
from urllib.parse import urljoin, urlsplit

import httpx
import typer

from kaos_cli.auth.login import _token_claims
from kaos_cli.cluster_http import local_service_url
from kaos_cli.config import load_config, session_token


DEFAULT_BROKER_URL = (
    "http://aib-agentic-identity-broker.aib-system.svc.cluster.local:8000"
)
DEFAULT_BROKER_ADMIN_URL = (
    "http://aib-agentic-identity-broker.aib-system.svc.cluster.local:14000/api"
)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def reauth_url(response) -> str | None:
    """Extract an AIB reauthorization URL from headers or a runtime outcome."""
    header_url = response.headers.get("x-kaos-reauth-url")
    if header_url:
        return header_url
    try:
        data = response.json()
        content = data.get("choices", [])[0].get("message", {}).get("content", "")
    except (AttributeError, IndexError, TypeError, ValueError):
        content = getattr(response, "text", "")
    if "reauth" not in content.lower() and "reconnect" not in content.lower():
        return None
    for candidate in _URL_RE.findall(content):
        cleaned = candidate.rstrip(".,;:!?)\"]}")
        if "/api/third-party/" in cleaned and "/oauth2/authorize" in cleaned:
            return cleaned
    return None


def service_id_from_reauth_url(url: str) -> str | None:
    """Return the service UUID embedded in an AIB reauthorization URL."""
    match = re.search(r"/api/third-party/([^/]+)/oauth2/authorize", urlsplit(url).path)
    return match.group(1) if match else None


def _broker_urls(config: dict) -> tuple[str, str]:
    auth = config.get("auth", {})
    return (
        auth.get("broker_url", "").rstrip("/") or DEFAULT_BROKER_URL,
        auth.get("broker_admin_url", "").rstrip("/") or DEFAULT_BROKER_ADMIN_URL,
    )


def _principal(config: dict, user: str) -> str:
    token = session_token(config, user)
    principal = _token_claims(token or "").get("sub")
    if not principal:
        raise ValueError(f"log in first: kaos auth login {user}")
    return str(principal)


def _request(method: str, url: str, principal: str) -> httpx.Response:
    with local_service_url(url) as local_url:
        return httpx.request(
            method,
            local_url,
            headers={"Host": urlsplit(url).netloc, "X-Remote-User": principal},
            follow_redirects=False,
            timeout=30.0,
        )


def _services(config: dict) -> list[dict]:
    _, admin_url = _broker_urls(config)
    with local_service_url(f"{admin_url}/services") as local_url:
        response = httpx.get(
            local_url,
            headers={"Host": urlsplit(admin_url).netloc},
            timeout=30.0,
        )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else data.get("items", [])


def _service(config: dict, name_or_id: str) -> dict:
    wanted = name_or_id.casefold()
    for service in _services(config):
        display_name = str(service.get("display_name", ""))
        words = re.findall(r"[a-z0-9]+", display_name.casefold())
        if name_or_id == str(service.get("id")) or wanted == "-".join(words) or wanted in words:
            return service
    raise ValueError(f"delegated service not found: {name_or_id}")


def service_alias(config: dict, service_id: str) -> str:
    """Resolve a service ID to its concise CLI name."""
    service = _service(config, service_id)
    words = re.findall(r"[a-z0-9]+", str(service.get("display_name", "")).casefold())
    return words[0] if words else service_id


def _active(config: dict, principal: str, service_id: str) -> bool:
    broker_url, _ = _broker_urls(config)
    response = _request("GET", f"{broker_url}/api/third-party/sessions", principal)
    response.raise_for_status()
    data = response.json().get("data", {})
    sessions = data if isinstance(data, list) else data.get("sessions", [])
    return any(
        str(session.get("service_id")) == service_id and not session.get("is_expired")
        for session in sessions
    )


def active_service_alias(config: dict, user: str, message: str = "") -> str | None:
    """Return the active delegated service most likely named by the message."""
    principal = _principal(config, user)
    broker_url, _ = _broker_urls(config)
    response = _request("GET", f"{broker_url}/api/third-party/sessions", principal)
    response.raise_for_status()
    data = response.json().get("data", {})
    sessions = data if isinstance(data, list) else data.get("sessions", [])
    active = [session for session in sessions if not session.get("is_expired")]
    for session in active:
        alias = re.findall(
            r"[a-z0-9]+", str(session.get("service_display_name", "")).casefold()
        )
        if alias and alias[0] in message.casefold():
            return alias[0]
    if len(active) == 1:
        words = re.findall(
            r"[a-z0-9]+", str(active[0].get("service_display_name", "")).casefold()
        )
        return words[0] if words else None
    return None


def _cluster_local(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(
        ".svc.cluster.local"
    )


def _authorize(config: dict, principal: str, service_id: str) -> None:
    broker_url, _ = _broker_urls(config)
    current = (
        f"{broker_url}/api/third-party/{service_id}/oauth2/authorize"
        f"?redirect_uri={broker_url}/consent/sessions"
    )
    for _ in range(6):
        response = _request("GET", current, principal)
        if response.is_redirect:
            current = urljoin(current, response.headers["location"])
            if not _cluster_local(current):
                typer.echo(f"Open this URL to approve access: {current}")
                typer.launch(current)
                for _ in range(60):
                    if _active(config, principal, service_id):
                        return
                    time.sleep(2)
                raise RuntimeError("timed out waiting for approval")
            continue
        response.raise_for_status()
        return
    raise RuntimeError("OAuth2 authorization used too many redirects")


def consent_command(service: str, user: str, disconnect: bool = False) -> None:
    """Create or revoke the user's AIB vault session for a delegated service."""
    try:
        config = load_config()
        principal = _principal(config, user)
        record = _service(config, service)
        service_id = str(record["id"])
        broker_url, _ = _broker_urls(config)
        if disconnect:
            response = _request(
                "DELETE", f"{broker_url}/api/third-party/{service_id}/session", principal
            )
            response.raise_for_status()
            typer.echo("✓ disconnected")
            return
        _authorize(config, principal, service_id)
        if not _active(config, principal, service_id):
            raise RuntimeError("broker did not create an active vault session")
    except (httpx.HTTPError, KeyError, RuntimeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"✓ connected — {user} can now use {service} through their agents")
