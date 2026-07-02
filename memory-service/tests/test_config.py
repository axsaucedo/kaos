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
    assert w.rolling_summary is False
    assert w.hard_event_cap == 2000


def test_short_term_tier_water_marks_default_from_budget():
    w = ShortTermTierConfig(token_budget=1000)
    # high_water defaults to the budget (fold trigger); low_water to half (fold target).
    assert w.high_water == 1000
    assert w.low_water == 500


def test_short_term_tier_explicit_water_marks_kept():
    w = ShortTermTierConfig(token_budget=1000, high_water=900, low_water=300)
    assert w.high_water == 900
    assert w.low_water == 300


def test_short_term_tier_rejects_inverted_water_marks():
    with pytest.raises(ValueError):
        ShortTermTierConfig(token_budget=1000, high_water=300, low_water=900)


def test_short_term_tier_rejects_high_water_above_budget():
    with pytest.raises(ValueError):
        ShortTermTierConfig(token_budget=1000, high_water=1200, low_water=500)


def test_short_term_tier_rejects_zero_hard_event_cap():
    with pytest.raises(ValueError):
        ShortTermTierConfig(hard_event_cap=0)


def test_short_term_tier_digest_retention_default_and_bound():
    assert ShortTermTierConfig().digest_retention == 20
    with pytest.raises(ValueError):
        ShortTermTierConfig(digest_retention=0)
