"""Keycloak re-minting for declared delegated third-party calls."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit

import httpx

from .identity import IdentityUnavailable
from .instrument import HEADER_SUBJECT_TOKEN, _as_bearer, ctx

_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


@dataclass
class _Config:
    issuer: str
    token_endpoint: str
    audience: str
    targets: list[str]


def _config() -> Optional[_Config]:
    raw = os.environ.get("KAOS_TOKEN_EXCHANGE_CONFIG", "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return _Config(
            issuer=str(data["issuer"]).rstrip("/"),
            token_endpoint=str(data["token_endpoint"]),
            audience=str(data["audience"]),
            targets=[str(target) for target in data["targets"]],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IdentityUnavailable(f"invalid token exchange configuration: {exc}") from exc


def _matches(url: Any, target: str) -> bool:
    request_url = urlsplit(str(url))
    target_url = urlsplit(target)
    if not target_url.scheme or not target_url.hostname:
        return False
    if (
        request_url.scheme.lower() != target_url.scheme.lower()
        or request_url.hostname != target_url.hostname
        or request_url.port != target_url.port
    ):
        return False
    target_path = target_url.path or "/"
    request_path = request_url.path or "/"
    return request_path == target_path.rstrip("/") or request_path.startswith(
        target_path.rstrip("/") + "/"
    )


def is_declared_target(url: Any) -> bool:
    config = _config()
    return bool(config and any(_matches(url, target) for target in config.targets))


def _subject_token() -> Optional[str]:
    token = ctx.get("subject_token")
    if not token or (ctx.get("principal") and ctx.get("principal") == ctx.get("actor")):
        return None
    return str(token)


def _credentials() -> tuple[str, str]:
    client_id = os.environ.get("AGENT_AUTH_CLIENT_ID", "")
    secret = ""
    secret_file = os.environ.get("AGENT_AUTH_CLIENT_SECRET_FILE", "")
    if secret_file:
        try:
            with open(secret_file, "r", encoding="utf-8") as fh:
                secret = fh.read().strip()
        except OSError:
            pass
    secret = secret or os.environ.get("AGENT_AUTH_CLIENT_SECRET", "")
    if not client_id or not secret:
        raise IdentityUnavailable(
            "declared third-party access requires AGENT_AUTH_CLIENT_ID and AGENT_AUTH_CLIENT_SECRET"
        )
    return client_id, secret


def _claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise IdentityUnavailable("token exchange returned an invalid JWT") from exc


def _parse(response: httpx.Response, config: _Config, subject_token: str, client_id: str) -> str:
    try:
        response.raise_for_status()
        token = response.json()["access_token"]
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise IdentityUnavailable(f"Keycloak token exchange failed: {exc}") from exc
    subject = _claims(subject_token).get("sub")
    claims = _claims(str(token))
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if (
        not subject
        or claims.get("iss", "").rstrip("/") != config.issuer
        or claims.get("sub") != subject
        or claims.get("azp") != client_id
        or audiences != [config.audience]
    ):
        raise IdentityUnavailable("Keycloak token exchange returned unexpected claims")
    return str(token)


def _exchange_request(
    client: Any, config: _Config, subject_token: str, client_id: str, secret: str
) -> httpx.Request:
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return client.build_request(
        "POST",
        config.token_endpoint,
        headers={"Authorization": f"Basic {basic}"},
        data={
            "grant_type": _GRANT,
            "subject_token": subject_token,
            "subject_token_type": _TOKEN_TYPE,
            "requested_token_type": _TOKEN_TYPE,
            "audience": config.audience,
        },
    )


def remint_request_sync(request: Any, send: Callable[..., httpx.Response]) -> bool:
    config = _config()
    subject_token = _subject_token()
    if (
        not config
        or not subject_token
        or not any(_matches(request.url, target) for target in config.targets)
    ):
        return False
    client_id, secret = _credentials()
    with httpx.Client() as client:
        response = send(client, _exchange_request(client, config, subject_token, client_id, secret))
    request.headers[HEADER_SUBJECT_TOKEN] = _as_bearer(
        _parse(response, config, subject_token, client_id)
    )
    return True


async def remint_request_async(
    request: Any, send: Callable[..., Awaitable[httpx.Response]]
) -> bool:
    config = _config()
    subject_token = _subject_token()
    if (
        not config
        or not subject_token
        or not any(_matches(request.url, target) for target in config.targets)
    ):
        return False
    client_id, secret = _credentials()
    async with httpx.AsyncClient() as client:
        response = await send(
            client, _exchange_request(client, config, subject_token, client_id, secret)
        )
    request.headers[HEADER_SUBJECT_TOKEN] = _as_bearer(
        _parse(response, config, subject_token, client_id)
    )
    return True
