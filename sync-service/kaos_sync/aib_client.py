"""AIB admin API client.

A thin idempotent wrapper over the AIB admin REST API used by the sync reconcile loop.
Pre-authentication is plain-header based: the configured principal is sent on every
request via the configured header (``X-Remote-User`` by default).

Transient failures (connection errors and ``5xx`` responses) are retried with bounded
exponential backoff so a briefly-unreachable or restarting broker does not fail a whole
reconcile pass; non-transient ``4xx`` responses are surfaced immediately.
"""

from __future__ import annotations

import time
from typing import List

import httpx

# Transient HTTP statuses worth retrying (server-side / gateway failures only).
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class AIBAdmin:
    """Idempotent client for the AIB admin API."""

    def __init__(
        self,
        base_url: str,
        principal: str,
        principal_header: str = "X-Remote-User",
        timeout: float = 10.0,
        client: httpx.Client | None = None,
        retry_max_attempts: int = 4,
        retry_base_delay_seconds: float = 0.5,
        sleep=time.sleep,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={principal_header: principal},
        )
        self._retry_max_attempts = max(1, retry_max_attempts)
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleep = sleep

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Issue a request, retrying transient connection/5xx failures with backoff.

        Retries are bounded by ``retry_max_attempts``; the delay grows exponentially from
        ``retry_base_delay_seconds``. A connection error on the final attempt is re-raised;
        a retryable status on the final attempt is returned to the caller to handle.
        """
        last_exc: Exception | None = None
        response: httpx.Response | None = None
        for attempt in range(self._retry_max_attempts):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
                response = None
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    return response
            if attempt < self._retry_max_attempts - 1:
                self._sleep(self._retry_base_delay_seconds * (2**attempt))
        if response is None:
            assert last_exc is not None
            raise last_exc
        return response

    def _list(self, collection: str) -> List[dict]:
        data = self._request("GET", f"/{collection}").json()
        if isinstance(data, dict):
            return data.get("items", [])
        return data

    def list(self, collection: str) -> List[dict]:
        """Return all items in a collection (``items`` envelope or bare list)."""
        return self._list(collection)

    def get(self, collection: str, resource_id: str) -> dict | None:
        """Return a single resource by id, or ``None`` if it does not exist (404)."""
        response = self._request("GET", f"/{collection}/{resource_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def create_or_get(self, collection: str, match_field: str, match_value: str, body: dict) -> str:
        """Create a resource, returning its id; if it already exists, return that id.

        Creation is attempted first; on a non-2xx response the collection is scanned for an
        item whose ``match_field`` equals ``match_value``, which makes the call idempotent
        across reconcile passes.
        """
        response = self._request("POST", f"/{collection}", json=body)
        if response.status_code // 100 == 2:
            return response.json()["id"]
        for item in self._list(collection):
            if item.get(match_field) == match_value:
                return item["id"]
        raise RuntimeError(
            f"failed to create or find {collection} {match_value}: "
            f"{response.status_code} {response.text}"
        )

    def delete(self, collection: str, resource_id: str) -> bool:
        """Delete a resource by id. Returns ``True`` if deleted, ``False`` if already gone.

        A ``404`` is treated as success (the desired end state -- absence -- already holds),
        so pruning is idempotent across passes.
        """
        response = self._request("DELETE", f"/{collection}/{resource_id}")
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def mint_credentials(self, agent_id: str) -> dict:
        """Mint client credentials for an agent and return the credential payload."""
        response = self._request("POST", f"/agents/{agent_id}/client-credentials")
        response.raise_for_status()
        return response.json()

    def revoke_credentials(self, agent_id: str) -> bool:
        """Revoke an agent's client credentials. Returns ``False`` if none existed (404)."""
        response = self._request("DELETE", f"/agents/{agent_id}/client-credentials")
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def close(self) -> None:
        self._client.close()
