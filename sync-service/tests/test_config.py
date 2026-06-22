"""Tests for environment-driven settings parsing."""

from __future__ import annotations

from kaos_sync.config import Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings.namespaces == ()
    assert settings.prune_enabled is True
    assert settings.metrics_port == 9090
    assert settings.health_port == 8080
    assert settings.retry_max_attempts == 4
    assert settings.retry_base_delay_seconds == 0.5


def test_overrides_from_env():
    settings = Settings.from_env(
        {
            "AIB_ADMIN_URL": "http://broker/api",
            "KAOS_SYNC_NAMESPACES": "a, b ,c",
            "KAOS_SYNC_PRUNE_ENABLED": "false",
            "KAOS_SYNC_METRICS_PORT": "1234",
            "KAOS_SYNC_HEALTH_PORT": "5678",
            "KAOS_SYNC_RETRY_MAX_ATTEMPTS": "7",
            "KAOS_SYNC_RETRY_BASE_DELAY_SECONDS": "0.25",
        }
    )
    assert settings.aib_admin_url == "http://broker/api"
    assert settings.namespaces == ("a", "b", "c")
    assert settings.prune_enabled is False
    assert settings.metrics_port == 1234
    assert settings.health_port == 5678
    assert settings.retry_max_attempts == 7
    assert settings.retry_base_delay_seconds == 0.25


def test_prune_enabled_truthy_values():
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "1"}).prune_enabled is True
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "yes"}).prune_enabled is True
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "off"}).prune_enabled is False
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "0"}).prune_enabled is False
