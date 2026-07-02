"""Unit tests for the typed storage configuration."""

import pytest

from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    ModelConfig,
    StorageConfig,
    ShortTermTierConfig,
)


def test_local_resolved_returns_local_block():
    cfg = StorageConfig(type="local", local=LocalStorage(path="/data"))
    block = cfg.resolved()
    assert isinstance(block, LocalStorage)
    assert block.provider == "chroma"
    assert block.path == "/data"


def test_external_resolved_returns_external_block():
    cfg = StorageConfig(type="external", external=ExternalStorage(dsn="postgresql://x"))
    block = cfg.resolved()
    assert isinstance(block, ExternalStorage)
    assert block.provider == "pgvector"
    assert block.embedding_dims == 1536


def test_local_without_block_raises():
    with pytest.raises(ValueError):
        StorageConfig(type="local").resolved()


def test_external_without_block_raises():
    with pytest.raises(ValueError):
        StorageConfig(type="external").resolved()


def test_model_config_defaults_key():
    m = ModelConfig(base_url="http://modelapi:8000/v1", model="gpt-4o-mini")
    assert m.api_key == "kaos"


def test_short_term_tier_defaults():
    w = ShortTermTierConfig()
    assert w.token_budget == 4096
    assert w.rolling_summary is True
    assert w.hard_event_cap == 2000
