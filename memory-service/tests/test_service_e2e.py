"""End-to-end integration: boot the app over real stores and drive write→recall→forget.

Runs the full service against real ``LongTermStore`` and ``ShortTermStore`` instances
(local Chroma+SQLite, and an external pgvector+Postgres variant behind the marker),
using a deterministic offline embedder and ``infer=False`` so no model endpoint is
contacted. Asserts the ``kaos.memory.*`` spans are emitted via an in-memory exporter.
"""

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    ModelConfig,
    StorageConfig,
    ShortTermTierConfig,
)
from kaos_memory.stores import LongTermStore
from kaos_memory.app import MemoryService, create_app
from kaos_memory.stores import ShortTermStore
from tests._fakes import DeterministicEmbedder

OFFLINE = ModelConfig(base_url="http://127.0.0.1:0/v1", model="offline", api_key="t")

USER_SCOPE = {"level": "user", "principal": "dave"}


@pytest.fixture(scope="module")
def _provider_exporter():
    # set_tracer_provider takes effect once per process; set it once for the module
    # and reuse the single exporter, clearing it per test.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def span_exporter(_provider_exporter):
    _provider_exporter.clear()
    return _provider_exporter


def _service(storage: StorageConfig, short_term_target: str) -> MemoryService:
    longterm = LongTermStore(storage, OFFLINE, OFFLINE)
    longterm._memory.embedding_model = DeterministicEmbedder()
    # Synchronous scheduler so the integration flow is deterministic.
    short_term = ShortTermStore(
        "local" if storage.type == "local" else "external",
        short_term_target,
        ShortTermTierConfig(),
        lambda p, f: p,
    )
    return MemoryService(longterm=longterm, short_term=short_term, scheduler=lambda thunk: thunk())


def _drive_and_assert(service: MemoryService, span_exporter, short_term_scope_target):
    client = TestClient(create_app(service))

    # Write a turn: durable short-term append + synchronous extraction (infer=False).
    w = client.post(
        "/v1/write",
        json={
            "scope": USER_SCOPE,
            "role": "user",
            "content": "the production cluster runs in eu-west-1",
            "infer": False,
        },
    )
    assert w.status_code == 202

    # Recall: short-term context is present; long-term recall may match the stored fact.
    r = client.post("/v1/recall", json={"scope": USER_SCOPE, "query": "where does the cluster run"})
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is False
    assert any("eu-west-1" in c for _, c in body["short_term"]["recent"])

    # Forget: clears both tiers.
    f = client.post("/v1/forget", json={"scope": USER_SCOPE})
    assert f.status_code == 200
    after = client.post("/v1/recall", json={"scope": USER_SCOPE, "query": "cluster"})
    assert after.json()["short_term"]["recent"] == []

    names = {s.name for s in span_exporter.get_finished_spans()}
    assert {"kaos.memory.write", "kaos.memory.recall", "kaos.memory.forget"} <= names


def test_local_mode_end_to_end(tmp_path, span_exporter):
    storage = StorageConfig(type="local", local=LocalStorage(path=str(tmp_path / "lt")))
    service = _service(storage, str(tmp_path / "shortterm.db"))
    _drive_and_assert(service, span_exporter, str(tmp_path / "shortterm.db"))


@pytest.mark.pgvector
def test_external_mode_end_to_end(pgvector_dsn, span_exporter):
    storage = StorageConfig(
        type="external",
        external=ExternalStorage(dsn=pgvector_dsn, collection_name="kaos_e2e", embedding_dims=64),
    )
    service = _service(storage, pgvector_dsn)
    try:
        _drive_and_assert(service, span_exporter, pgvector_dsn)
    finally:
        # Clean the short-term table rows for this scope so reruns are deterministic.
        service.short_term.close()
