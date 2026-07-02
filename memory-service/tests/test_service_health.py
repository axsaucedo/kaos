"""Health and readiness surface tests for the memory service."""

from fastapi.testclient import TestClient

from kaos_memory.service import MemoryService, create_app


class _OkStore:
    def ping(self) -> None:
        return None


class _BrokenStore:
    def ping(self) -> None:
        raise RuntimeError("store down")


def _client(longterm, short_term) -> TestClient:
    return TestClient(create_app(MemoryService(longterm=longterm, short_term=short_term)))


def test_healthz_is_independent_of_store_state():
    client = _client(_BrokenStore(), _BrokenStore())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ok_when_both_stores_reachable():
    client = _client(_OkStore(), _OkStore())
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["stores"] == {"short_term": True, "longterm": True}


def test_readyz_503_when_a_store_is_unreachable():
    client = _client(longterm=_BrokenStore(), short_term=_OkStore())
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["stores"]["short_term"] is True
    assert "RuntimeError" in body["stores"]["longterm"]
