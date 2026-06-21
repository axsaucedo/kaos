"""Runtime configuration for the KAOS sync service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Settings sourced from the environment.

    aib_admin_url: base URL of the AIB admin API (including the ``/api`` suffix).
    aib_principal: principal sent in the pre-auth header to the AIB admin API.
    aib_principal_header: header carrying the pre-authenticated principal.
    namespaces: namespaces to watch; empty means cluster-wide.
    credential_secret_prefix: prefix for per-agent credential Secret names.
    reconcile_interval_seconds: delay between reconcile passes.
    """

    aib_admin_url: str = "http://localhost:14000/api"
    aib_principal: str = "kaos-sync"
    aib_principal_header: str = "X-Remote-User"
    namespaces: tuple[str, ...] = ()
    credential_secret_prefix: str = "kaos-aib"
    reconcile_interval_seconds: int = 30
    request_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        namespaces = tuple(
            n.strip() for n in env.get("KAOS_SYNC_NAMESPACES", "").split(",") if n.strip()
        )
        return cls(
            aib_admin_url=env.get("AIB_ADMIN_URL", cls.aib_admin_url),
            aib_principal=env.get("AIB_PRINCIPAL", cls.aib_principal),
            aib_principal_header=env.get("AIB_PRINCIPAL_HEADER", cls.aib_principal_header),
            namespaces=namespaces,
            credential_secret_prefix=env.get(
                "KAOS_SYNC_CREDENTIAL_SECRET_PREFIX", cls.credential_secret_prefix
            ),
            reconcile_interval_seconds=int(
                env.get("KAOS_SYNC_RECONCILE_INTERVAL_SECONDS", cls.reconcile_interval_seconds)
            ),
            request_timeout_seconds=float(
                env.get("KAOS_SYNC_REQUEST_TIMEOUT_SECONDS", cls.request_timeout_seconds)
            ),
        )
