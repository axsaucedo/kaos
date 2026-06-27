"""Optional off-gateway client for the broker's access-check and token endpoints.

The KAOS gateway already performs actor/subject authentication, edge authorization
(``ext_authz``) and delegated token exchange (``ext_proc``) for traffic that flows
through it. This client is for the **off-gateway** case: a custom server or tool that
wants to ask the broker directly whether the calling agent may act on a resource, or to
obtain a delegated third-party token, without sitting behind the gateway. It is not the
enforcement boundary — it is a convenience over the broker's HTTP API.

Principal / actor / request-id default from the request-local :data:`aib.ctx` so an
in-request caller does not have to thread them manually.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from .identity import AIBUnavailable, actor_token, actor_token_async
from .instrument import HEADER_ACCESS_REASON, HEADER_REAUTH_URL, ctx

_TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
# Reasons (or reason prefixes) that mean the user must re-authenticate / re-consent.
_REAUTH_REASONS = ("reauth", "consent", "user_action_required", "reauthentication_required")


class AccessDenied(RuntimeError):
    """Raised by :meth:`Client.require_access` when access is not allowed."""

    def __init__(self, decision: "AccessDecision") -> None:
        super().__init__(f"access denied: {decision.reason or 'not allowed'}")
        self.decision = decision


class ReauthenticationRequired(AccessDenied):
    """Raised when the denial is recoverable by user re-authentication / re-consent."""

    def __init__(self, decision: "AccessDecision") -> None:
        super().__init__(decision)
        self.reauth_url = decision.reauth_url


@dataclass
class AccessRequest:
    """A resource-level access-check question."""

    resource: str
    action: str = "access"
    actor_token: Optional[str] = None
    principal: Optional[str] = None
    request_id: Optional[str] = None


@dataclass
class AccessDecision:
    """The broker's structured allow/deny decision."""

    allowed: bool
    reason: str = ""
    actor: str = ""
    resource: str = ""
    action: str = ""
    reauth_url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def requires_reauth(self) -> bool:
        """True when the denial is recoverable via user re-authentication / re-consent."""
        reason = (self.reason or "").lower()
        return bool(self.reauth_url) or any(reason.startswith(r) for r in _REAUTH_REASONS)


@dataclass
class TokenResult:
    """A delegated token returned by the broker token endpoint."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 0
    scope: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


def _default_base_url(base_url: Optional[str]) -> str:
    return base_url or os.environ.get("AGENT_AUTH_BASE_URL", "") or ""


def _default_token_endpoint(token_endpoint: Optional[str], base_url: str) -> str:
    if token_endpoint:
        return token_endpoint
    env = os.environ.get("AGENT_AUTH_TOKEN_ENDPOINT", "")
    if env:
        return env
    if base_url:
        return f"{base_url.rstrip('/')}/oauth2/token"
    return ""


def _resolve_actor_token(explicit: Optional[str]) -> Optional[str]:
    """Actor token to present: explicit, else managed lifecycle, else request ctx."""
    if explicit:
        return explicit
    managed = actor_token()
    if managed:
        return managed
    return ctx.get("actor_token")


def _build_check_body(req: AccessRequest) -> Dict[str, Any]:
    body: Dict[str, Any] = {"resource": req.resource, "action": req.action or "access"}
    token = _resolve_actor_token(req.actor_token)
    if token:
        body["actor_token"] = token
    return body


def _parse_decision(data: Dict[str, Any]) -> AccessDecision:
    return AccessDecision(
        allowed=bool(data.get("allowed", False)),
        reason=str(data.get("reason", "") or ""),
        actor=str(data.get("actor", "") or ""),
        resource=str(data.get("resource", "") or ""),
        action=str(data.get("action", "") or ""),
        reauth_url=data.get("reauth_url") or data.get("error_uri") or None,
        raw=data,
    )


def _parse_token(data: Dict[str, Any]) -> TokenResult:
    token = data.get("access_token")
    if not token:
        raise AIBUnavailable("broker token response missing access_token")
    return TokenResult(
        access_token=token,
        token_type=str(data.get("token_type", "Bearer") or "Bearer"),
        expires_in=int(data.get("expires_in", 0) or 0),
        scope=str(data.get("scope", "") or ""),
        raw=data,
    )


def _exchange_form(subject_token: str, audience: str, scopes: str) -> Dict[str, str]:
    form = {
        "grant_type": _TOKEN_EXCHANGE_GRANT,
        "subject_token": subject_token,
        "subject_token_type": _ACCESS_TOKEN_TYPE,
    }
    if audience:
        form["audience"] = audience
    if scopes:
        form["scope"] = scopes
    return form


def _raise_for_decision(decision: AccessDecision) -> None:
    if decision.allowed:
        return
    if decision.requires_reauth:
        raise ReauthenticationRequired(decision)
    raise AccessDenied(decision)


def outcome_from_response(
    response: Any, *, resource: str = "", action: str = ""
) -> Optional[AccessDecision]:
    """Map a KAOS-gateway enforcement response to a structured :class:`AccessDecision`.

    Reads only response *headers* — never the body — so it is safe to call on any
    instrumented outbound response, including streaming ones. Returns ``None`` for
    any response without the gateway enforcement header (``x-kaos-access-reason``),
    so ordinary traffic and non-KAOS 4xx/5xx responses are unaffected. When the
    header is present the decision is always a denial: an ext_authz denial carries
    the platform/user reason with no URL, while an ext_proc re-auth response carries
    ``third_party_reauth_required`` plus a ``x-kaos-reauth-url``.
    """
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    reason = headers.get(HEADER_ACCESS_REASON)
    if not reason:
        return None
    return AccessDecision(
        allowed=False,
        reason=str(reason),
        resource=resource,
        action=action,
        reauth_url=headers.get(HEADER_REAUTH_URL) or None,
    )


def raise_for_gateway_outcome(response: Any, *, resource: str = "", action: str = "") -> None:
    """Raise a typed outcome when ``response`` carries a KAOS-gateway denial.

    A no-op for any response that does not carry the gateway enforcement header,
    so it is safe to call unconditionally on every instrumented outbound response.
    A ``user_grant_required`` / ``platform_grant_missing`` ext_authz denial raises
    :class:`AccessDenied`; an ext_proc ``third_party_reauth_required`` (which carries
    a re-auth URL) raises :class:`ReauthenticationRequired`.
    """
    decision = outcome_from_response(response, resource=resource, action=action)
    if decision is not None:
        _raise_for_decision(decision)


class Client:
    """Synchronous off-gateway client over the broker access-check + token endpoints."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        token_endpoint: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = _default_base_url(base_url)
        self._token_endpoint = _default_token_endpoint(token_endpoint, self._base_url)
        self._timeout = timeout

    def _access_check_url(self) -> str:
        return f"{self._base_url.rstrip('/')}/api/access/check"

    def check_access(
        self,
        resource: str,
        action: str = "access",
        *,
        actor_token: Optional[str] = None,
        principal: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> AccessDecision:
        """Ask the broker whether the calling agent may perform ``action`` on ``resource``."""
        req = AccessRequest(
            resource=resource,
            action=action,
            actor_token=actor_token,
            principal=principal or ctx.get("principal"),
            request_id=request_id or ctx.get("request_id"),
        )
        try:
            resp = httpx.post(
                self._access_check_url(),
                json=_build_check_body(req),
                headers=_ctx_headers(req),
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIBUnavailable(f"access-check request failed: {exc}") from exc
        return _parse_decision(resp.json())

    def require_access(
        self, resource: str, action: str = "access", **kwargs: Any
    ) -> AccessDecision:
        """Like :meth:`check_access` but raise on a non-allow decision."""
        decision = self.check_access(resource, action, **kwargs)
        _raise_for_decision(decision)
        return decision

    def exchange_token(
        self, subject_token: str, audience: str = "", scopes: str = ""
    ) -> TokenResult:
        """Exchange a subject token for a delegated token (RFC 8693)."""
        try:
            resp = httpx.post(
                self._token_endpoint,
                data=_exchange_form(subject_token, audience, scopes),
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIBUnavailable(f"token exchange failed: {exc}") from exc
        return _parse_token(resp.json())

    def get_token(self, resource: str, scopes: str = "") -> TokenResult:
        """Obtain a delegated token for ``resource`` using the request's subject token."""
        subject_token = ctx.get("subject_token")
        if not subject_token:
            raise AIBUnavailable("no subject token in context for get_token")
        return self.exchange_token(subject_token, audience=resource, scopes=scopes)


class AsyncClient:
    """Asynchronous counterpart of :class:`Client`."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        token_endpoint: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = _default_base_url(base_url)
        self._token_endpoint = _default_token_endpoint(token_endpoint, self._base_url)
        self._timeout = timeout

    def _access_check_url(self) -> str:
        return f"{self._base_url.rstrip('/')}/api/access/check"

    async def check_access(
        self,
        resource: str,
        action: str = "access",
        *,
        actor_token: Optional[str] = None,
        principal: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> AccessDecision:
        """Async variant of :meth:`Client.check_access`."""
        req = AccessRequest(
            resource=resource,
            action=action,
            actor_token=await _resolve_actor_token_async(actor_token),
            principal=principal or ctx.get("principal"),
            request_id=request_id or ctx.get("request_id"),
        )
        body: Dict[str, Any] = {"resource": req.resource, "action": req.action or "access"}
        if req.actor_token:
            body["actor_token"] = req.actor_token
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._access_check_url(), json=body, headers=_ctx_headers(req)
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIBUnavailable(f"access-check request failed: {exc}") from exc
        return _parse_decision(resp.json())

    async def require_access(
        self, resource: str, action: str = "access", **kwargs: Any
    ) -> AccessDecision:
        """Async variant of :meth:`Client.require_access`."""
        decision = await self.check_access(resource, action, **kwargs)
        _raise_for_decision(decision)
        return decision

    async def exchange_token(
        self, subject_token: str, audience: str = "", scopes: str = ""
    ) -> TokenResult:
        """Async variant of :meth:`Client.exchange_token`."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._token_endpoint, data=_exchange_form(subject_token, audience, scopes)
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIBUnavailable(f"token exchange failed: {exc}") from exc
        return _parse_token(resp.json())

    async def get_token(self, resource: str, scopes: str = "") -> TokenResult:
        """Async variant of :meth:`Client.get_token`."""
        subject_token = ctx.get("subject_token")
        if not subject_token:
            raise AIBUnavailable("no subject token in context for get_token")
        return await self.exchange_token(subject_token, audience=resource, scopes=scopes)


async def _resolve_actor_token_async(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    managed = await actor_token_async()
    if managed:
        return managed
    return ctx.get("actor_token")


def _ctx_headers(req: AccessRequest) -> Dict[str, str]:
    """Correlation/principal headers carried alongside an access-check request."""
    headers: Dict[str, str] = {}
    if req.principal:
        headers["x-principal"] = req.principal
    if req.request_id:
        headers["x-request-id"] = req.request_id
    return headers
