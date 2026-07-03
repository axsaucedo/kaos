"""Shared fixtures: an offline ModelConfig and an optional pgvector container DSN."""

import os

import pytest

from kaos_memory.config import ModelConfig

# A model binding that is structurally valid but never contacted: the long-term
# tests use a deterministic embedder and infer=False so no model call is made.
OFFLINE_MODEL = ModelConfig(base_url="http://127.0.0.1:0/v1", model="offline", api_key="test")


@pytest.fixture
def offline_models():
    return {"summarization": OFFLINE_MODEL, "embedding": OFFLINE_MODEL}


@pytest.fixture
def pgvector_dsn():
    """DSN for a local pgvector container, or skip if it is not configured.

    Run one with:
        docker run -d --name kaos-pgv -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=memdb \\
            -p 55432:5432 pgvector/pgvector:pg16
    and export KAOS_TEST_PGVECTOR_DSN=postgresql://postgres:pw@localhost:55432/memdb
    """
    dsn = os.environ.get("KAOS_TEST_PGVECTOR_DSN")
    if not dsn:
        pytest.skip("KAOS_TEST_PGVECTOR_DSN not set; pgvector container unavailable")
    return dsn
