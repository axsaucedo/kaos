"""Tests for the AIB admin client: list/get/delete/revoke and bounded retry.

A fake ``httpx`` transport drives deterministic responses (including transient failures)
without a live broker, so retry/backoff and 404 semantics are exercised in isolation.
"""

from __future__ import annotations

import httpx
import pytest

from kaos_sync.aib_client import AIBAdmin


def _client(handler, **kwargs) -> AIBAdmin:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="http://aib.test",
        transport=transport,
        headers={"X-Remote-User": "kaos-sync"},
    )
    # sleep is a no-op so retry tests do not actually wait.
    return AIBAdmin(
        base_url="http://aib.test",
        principal="kaos-sync",
        client=http,
        sleep=lambda _: None,
        **kwargs,
    )


def test_list_unwraps_items_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/agents"
        return httpx.Response(200, json={"items": [{"id": "a1"}, {"id": "a2"}]})

    aib = _client(handler)
    assert aib.list("agents") == [{"id": "a1"}, {"id": "a2"}]


def test_list_accepts_bare_list() -> None:
    aib = _client(lambda req: httpx.Response(200, json=[{"id": "a1"}]))
    assert aib.list("agents") == [{"id": "a1"}]


def test_get_returns_none_on_404() -> None:
    aib = _client(lambda req: httpx.Response(404, json={"error": "not found"}))
    assert aib.get("agents", "missing") is None


def test_get_returns_resource() -> None:
    aib = _client(lambda req: httpx.Response(200, json={"id": "a1", "name": "x"}))
    assert aib.get("agents", "a1") == {"id": "a1", "name": "x"}


def test_delete_returns_true_when_deleted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/agents/a1"
        return httpx.Response(204)

    assert _client(handler).delete("agents", "a1") is True


def test_delete_returns_false_when_already_gone() -> None:
    aib = _client(lambda req: httpx.Response(404))
    assert aib.delete("agents", "gone") is False


def test_revoke_credentials_true_and_false() -> None:
    assert _client(lambda req: httpx.Response(204)).revoke_credentials("a1") is True
    assert _client(lambda req: httpx.Response(404)).revoke_credentials("a1") is False


def test_retry_then_succeed_on_transient_5xx() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"items": []})

    aib = _client(handler, retry_max_attempts=4, retry_base_delay_seconds=0.0)
    assert aib.list("agents") == []
    assert calls["n"] == 3


def test_retry_then_succeed_on_connection_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json=[])

    aib = _client(handler, retry_max_attempts=3, retry_base_delay_seconds=0.0)
    assert aib.list("agents") == []
    assert calls["n"] == 2


def test_retry_exhausted_connection_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    aib = _client(handler, retry_max_attempts=2, retry_base_delay_seconds=0.0)
    with pytest.raises(httpx.ConnectError):
        aib.list("agents")


def test_retry_exhausted_5xx_surfaces_to_caller() -> None:
    aib = _client(
        lambda req: httpx.Response(500, text="boom"),
        retry_max_attempts=2,
        retry_base_delay_seconds=0.0,
    )
    # delete() raises for status on the final non-404 5xx response.
    with pytest.raises(httpx.HTTPStatusError):
        aib.delete("agents", "a1")


def test_create_or_get_creates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(201, json={"id": "new"})

    assert _client(handler).create_or_get("agents", "name", "x", {"name": "x"}) == "new"


def test_create_or_get_falls_back_to_existing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, text="exists")
        return httpx.Response(200, json={"items": [{"id": "old", "name": "x"}]})

    assert _client(handler).create_or_get("agents", "name", "x", {"name": "x"}) == "old"
