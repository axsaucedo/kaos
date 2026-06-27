"""AIB admin API client.

A thin idempotent wrapper over the AIB admin REST API used by the sync reconcile loop.
Pre-authentication is plain-header based: the configured principal is sent on every
request via the configured header (``X-Remote-User`` by default).
"""

from __future__ import annotations

import httpx


class AIBAdmin:
    """Idempotent client for the AIB admin API."""

    def __init__(
        self,
        base_url: str,
        principal: str,
        principal_header: str = "X-Remote-User",
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={principal_header: principal},
        )

    def _list(self, collection: str) -> list[dict]:
        data = self._client.get(f"/{collection}").json()
        if isinstance(data, dict):
            return data.get("items", [])
        return data

    def create_or_get(self, collection: str, match_field: str, match_value: str, body: dict) -> str:
        """Create a resource, returning its id; if it already exists, return that id.

        Creation is attempted first; on a non-2xx response the collection is scanned for an
        item whose ``match_field`` equals ``match_value``, which makes the call idempotent
        across reconcile passes.
        """
        response = self._client.post(f"/{collection}", json=body)
        if response.status_code // 100 == 2:
            return response.json()["id"]
        for item in self._list(collection):
            if item.get(match_field) == match_value:
                return item["id"]
        raise RuntimeError(
            f"failed to create or find {collection} {match_value}: "
            f"{response.status_code} {response.text}"
        )

    def mint_credentials(self, agent_id: str) -> dict:
        """Mint client credentials for an agent and return the credential payload."""
        response = self._client.post(f"/agents/{agent_id}/client-credentials")
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()
