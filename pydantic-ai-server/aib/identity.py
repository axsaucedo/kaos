"""Machine actor-token lifecycle for the agent's own identity.

The propagation SDK (:mod:`aib.instrument`) forwards identities but does not *mint*
them. This module lets an agent authenticate as itself without a static, pre-minted
token: it acquires the agent **actor** token via an OAuth2 ``client_credentials`` grant
against the configured broker, caches it with refresh-ahead so the request path rarely
blocks, single-flights concurrent refreshes, backs off on broker unavailability, and
**fails closed** — it never hands back an empty or expired token as if it were valid.

Configuration comes from the provider-agnostic ``AGENT_AUTH_*`` environment the operator
injects into the agent pod: ``AGENT_AUTH_CLIENT_ID``, ``AGENT_AUTH_CLIENT_SECRET`` and
``AGENT_AUTH_TOKEN_ENDPOINT`` (or ``AGENT_AUTH_ISSUER`` from which the token endpoint is
derived). The minted token's subject is the agent's logical identity, which the operator
also exports as ``AGENT_AUTH_IDENTITY``.

When no credentials are configured the module is inert: :func:`actor_token` returns
``None`` and the existing static-token / simulation path is unchanged.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Optional

import httpx

# Refresh when this fraction of the token lifetime remains (refresh-ahead at ~80% TTL).
_DEFAULT_REFRESH_FRACTION = 0.2
# Bounded retry/backoff for the client_credentials grant before failing closed.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.2
_BACKOFF_CAP_SECONDS = 2.0
# Assumed lifetime when the token response omits ``expires_in``.
_FALLBACK_LIFETIME_SECONDS = 300.0


class AIBUnavailable(RuntimeError):
    """Raised when a fresh actor token cannot be obtained from the broker.

    The lifecycle fails closed: callers must treat this as an authentication failure
    rather than proceeding with a missing or stale token.
    """


def _derive_token_endpoint(token_endpoint: str, issuer: str) -> str:
    """Token endpoint, preferring an explicit value, else ``<issuer>/oauth2/token``."""
    if token_endpoint:
        return token_endpoint
    if issuer:
        return f"{issuer.rstrip('/')}/oauth2/token"
    return ""


class _Credential:
    """Source of the client secret: a projected-volume file when configured, else env.

    When a ``secret_file`` is set the contents are cached and re-read only when the file's
    mtime changes, so a rotated Kubernetes Secret is picked up on the next acquire without
    a process restart and without a background watcher. A missing/unreadable file falls
    back to the env secret (covers the pod-starts-before-Secret race).
    """

    def __init__(
        self,
        *,
        secret_env: str = "AGENT_AUTH_CLIENT_SECRET",
        secret_file: Optional[str] = None,
    ) -> None:
        self._secret_env = secret_env
        self._secret_file = secret_file
        self._cached_secret: Optional[str] = None
        self._cached_mtime: Optional[float] = None

    def _env_secret(self) -> str:
        return os.environ.get(self._secret_env, "") or ""

    def secret(self) -> str:
        """Current client secret (file-first, env fallback; empty when unset)."""
        if not self._secret_file:
            return self._env_secret()
        try:
            mtime = os.path.getmtime(self._secret_file)
        except OSError:
            return self._env_secret()
        if self._cached_secret is None or mtime != self._cached_mtime:
            try:
                with open(self._secret_file, "r", encoding="utf-8") as fh:
                    self._cached_secret = fh.read().strip()
                self._cached_mtime = mtime
            except OSError:
                return self._env_secret()
        return self._cached_secret or ""

    def reload(self) -> None:
        """Force the next :meth:`secret` to re-read the file (e.g. after a rotation 401)."""
        self._cached_secret = None
        self._cached_mtime = None


class ActorTokenManager:
    """Acquires and caches the agent actor token via ``client_credentials``.

    The manager serves a cached token until the refresh-ahead point (``refresh_fraction``
    of the lifetime remaining), then transparently re-acquires. Refreshes are
    single-flighted across both sync and async callers. On broker failure it retries with
    bounded backoff and then raises :class:`AIBUnavailable`; a still-valid cached token is
    preferred over failing, but an absent/expired token never silently passes.
    """

    def __init__(
        self,
        *,
        token_endpoint: str,
        client_id: str,
        credential: _Credential,
        scope: str = "",
        refresh_fraction: float = _DEFAULT_REFRESH_FRACTION,
    ) -> None:
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._credential = credential
        self._scope = scope
        self._refresh_fraction = refresh_fraction
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._refresh_at = 0.0
        self._sync_lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """True when the manager has enough to attempt a grant."""
        return bool(self._token_endpoint and self._client_id and self._credential.secret())

    def _cached_valid(self) -> Optional[str]:
        """Return the cached token if it is still within its lifetime, else ``None``."""
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        return None

    def _needs_refresh(self) -> bool:
        return self._token is None or time.monotonic() >= self._refresh_at

    def _store(self, token: str, expires_in: float) -> None:
        now = time.monotonic()
        lifetime = expires_in if expires_in > 0 else _FALLBACK_LIFETIME_SECONDS
        self._token = token
        self._expires_at = now + lifetime
        self._refresh_at = now + lifetime * (1.0 - self._refresh_fraction)

    def _grant_params(self) -> dict[str, str]:
        params = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._credential.secret(),
        }
        if self._scope:
            params["scope"] = self._scope
        return params

    @staticmethod
    def _parse(response: httpx.Response) -> tuple[str, float]:
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise AIBUnavailable("broker token response missing access_token")
        return token, float(data.get("expires_in", 0) or 0)

    # --- sync ---------------------------------------------------------------

    def token(self) -> Optional[str]:
        """Return a fresh actor token, refreshing ahead of expiry. ``None`` if inert."""
        if not self.configured:
            return None
        if not self._needs_refresh():
            return self._token
        with self._sync_lock:
            if not self._needs_refresh():
                return self._token
            try:
                self._store(*self._acquire_sync())
            except AIBUnavailable:
                cached = self._cached_valid()
                if cached is not None:
                    return cached
                raise
        return self._token

    def force_refresh(self) -> Optional[str]:
        """Invalidate the cache and acquire a new token synchronously."""
        self.invalidate()
        return self.token()

    def invalidate(self) -> None:
        """Drop the cached token so the next :meth:`token` re-acquires."""
        with self._sync_lock:
            self._token = None
            self._expires_at = 0.0
            self._refresh_at = 0.0

    def _acquire_sync(self) -> tuple[str, float]:
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = httpx.post(self._token_endpoint, data=self._grant_params(), timeout=10.0)
                if resp.status_code == 401:
                    self._credential.reload()
                resp.raise_for_status()
                return self._parse(resp)
            except (httpx.HTTPError, AIBUnavailable) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_backoff(attempt))
        raise AIBUnavailable(f"could not acquire actor token: {last_exc}") from last_exc

    # --- async --------------------------------------------------------------

    async def token_async(self) -> Optional[str]:
        """Async variant of :meth:`token`."""
        if not self.configured:
            return None
        if not self._needs_refresh():
            return self._token
        async with self._async_lock:
            if not self._needs_refresh():
                return self._token
            try:
                self._store(*await self._acquire_async())
            except AIBUnavailable:
                cached = self._cached_valid()
                if cached is not None:
                    return cached
                raise
        return self._token

    async def force_refresh_async(self) -> Optional[str]:
        """Async variant of :meth:`force_refresh`."""
        self.invalidate()
        return await self.token_async()

    async def _acquire_async(self) -> tuple[str, float]:
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(self._token_endpoint, data=self._grant_params())
                if resp.status_code == 401:
                    self._credential.reload()
                resp.raise_for_status()
                return self._parse(resp)
            except (httpx.HTTPError, AIBUnavailable) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(_backoff(attempt))
        raise AIBUnavailable(f"could not acquire actor token: {last_exc}") from last_exc


def _backoff(attempt: int) -> float:
    """Bounded exponential backoff for grant retries."""
    return min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_CAP_SECONDS)


# --- process-global manager + module accessors --------------------------------

_manager: Optional[ActorTokenManager] = None


def instrument_agent_identity(
    *,
    token_endpoint_env: str = "AGENT_AUTH_TOKEN_ENDPOINT",
    issuer_env: str = "AGENT_AUTH_ISSUER",
    client_id_env: str = "AGENT_AUTH_CLIENT_ID",
    client_secret_env: str = "AGENT_AUTH_CLIENT_SECRET",
    client_secret_file_env: str = "AGENT_AUTH_CLIENT_SECRET_FILE",
    client_secret_file: Optional[str] = None,
    scope: str = "",
    refresh_fraction: float = _DEFAULT_REFRESH_FRACTION,
) -> Optional[ActorTokenManager]:
    """Configure the process-global managed actor-token lifecycle.

    Reads the broker coordinates from the provider-agnostic ``AGENT_AUTH_*`` environment
    the operator injects. The client secret is sourced file-first from
    ``client_secret_file`` (or the ``AGENT_AUTH_CLIENT_SECRET_FILE`` env when not passed
    explicitly), falling back to ``AGENT_AUTH_CLIENT_SECRET``; a rotated file is reloaded
    on its next use. Returns the manager, or ``None`` when no credentials are present (the
    static-token / simulation path then remains in effect). Safe to call repeatedly.
    """
    global _manager
    token_endpoint = _derive_token_endpoint(
        os.environ.get(token_endpoint_env, ""), os.environ.get(issuer_env, "")
    )
    client_id = os.environ.get(client_id_env, "")
    secret_file = client_secret_file or os.environ.get(client_secret_file_env, "") or None
    credential = _Credential(secret_env=client_secret_env, secret_file=secret_file)
    manager = ActorTokenManager(
        token_endpoint=token_endpoint,
        client_id=client_id,
        credential=credential,
        scope=scope,
        refresh_fraction=refresh_fraction,
    )
    if not manager.configured:
        _manager = None
        return None
    _manager = manager
    return manager


def get_manager() -> Optional[ActorTokenManager]:
    """Return the configured process-global manager, if any."""
    return _manager


def reset_manager() -> None:
    """Clear the process-global manager (primarily for tests)."""
    global _manager
    _manager = None


def actor_token() -> Optional[str]:
    """Fresh managed actor token, or ``None`` when no managed identity is configured."""
    if _manager is None:
        return None
    return _manager.token()


async def actor_token_async() -> Optional[str]:
    """Async variant of :func:`actor_token`."""
    if _manager is None:
        return None
    return await _manager.token_async()
