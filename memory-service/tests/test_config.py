"""Unit tests for the typed storage configuration."""

import pytest

from kaos_memory.config import (
    ExternalStorage,
    LocalStorage,
    MemorySettings,
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


def test_short_term_tier_compaction_marks_default_from_budget():
    w = ShortTermTierConfig(token_budget=1000)
    # compaction_trigger defaults to the budget (fold trigger); compaction_target to half (fold target).
    assert w.compaction_trigger == 1000
    assert w.compaction_target == 500


def test_short_term_tier_explicit_compaction_marks_kept():
    w = ShortTermTierConfig(token_budget=1000, compaction_trigger=900, compaction_target=300)
    assert w.compaction_trigger == 900
    assert w.compaction_target == 300


def test_short_term_tier_rejects_inverted_compaction_marks():
    with pytest.raises(ValueError):
        ShortTermTierConfig(token_budget=1000, compaction_trigger=300, compaction_target=900)


def test_short_term_tier_rejects_compaction_trigger_above_budget():
    with pytest.raises(ValueError):
        ShortTermTierConfig(token_budget=1000, compaction_trigger=1200, compaction_target=500)


def test_short_term_tier_rejects_zero_hard_event_cap():
    with pytest.raises(ValueError):
        ShortTermTierConfig(hard_event_cap=0)


def test_short_term_tier_digest_retention_default_and_bound():
    assert ShortTermTierConfig().digest_retention == 20
    with pytest.raises(ValueError):
        ShortTermTierConfig(digest_retention=0)


def test_settings_short_term_tier_mirrors_water_mark_and_digest_knobs():
    settings = MemorySettings(
        token_budget=1000,
        compaction_trigger=900,
        compaction_target=400,
        hard_event_cap=50,
        digest_retention=7,
        rolling_summary=True,
    )
    tier = settings.short_term_tier()
    assert (tier.token_budget, tier.compaction_trigger, tier.compaction_target) == (1000, 900, 400)
    assert (tier.hard_event_cap, tier.digest_retention, tier.rolling_summary) == (50, 7, True)


def test_settings_short_term_tier_propagates_water_mark_constraint():
    with pytest.raises(ValueError):
        MemorySettings(
            token_budget=1000, compaction_trigger=400, compaction_target=900
        ).short_term_tier()


def test_settings_request_concurrency_default():
    assert MemorySettings().request_concurrency == 8
