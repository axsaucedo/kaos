"""Tests for environment-driven settings parsing."""

from __future__ import annotations

from kaos_sync.config import Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings.namespaces == ()
    assert settings.prune_enabled is True
    assert settings.health_port == 8080
    assert settings.retry_max_attempts == 4
    assert settings.retry_base_delay_seconds == 0.5


def test_overrides_from_env():
    settings = Settings.from_env(
        {
            "AIB_ADMIN_URL": "http://broker/api",
            "KAOS_SYNC_NAMESPACES": "a, b ,c",
            "KAOS_SYNC_PRUNE_ENABLED": "false",
            "KAOS_SYNC_HEALTH_PORT": "5678",
            "KAOS_SYNC_RETRY_MAX_ATTEMPTS": "7",
            "KAOS_SYNC_RETRY_BASE_DELAY_SECONDS": "0.25",
        }
    )
    assert settings.aib_admin_url == "http://broker/api"
    assert settings.namespaces == ("a", "b", "c")
    assert settings.prune_enabled is False
    assert settings.health_port == 5678
    assert settings.retry_max_attempts == 7
    assert settings.retry_base_delay_seconds == 0.25


def test_prune_enabled_truthy_values():
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "1"}).prune_enabled is True
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "yes"}).prune_enabled is True
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "off"}).prune_enabled is False
    assert Settings.from_env({"KAOS_SYNC_PRUNE_ENABLED": "0"}).prune_enabled is False


def test_watch_defaults_and_overrides():
    assert Settings.from_env({}).watch_enabled is True
    assert Settings.from_env({}).watch_debounce_seconds == 1.0
    settings = Settings.from_env(
        {
            "KAOS_SYNC_WATCH_ENABLED": "false",
            "KAOS_SYNC_WATCH_DEBOUNCE_SECONDS": "2.5",
        }
    )
    assert settings.watch_enabled is False
    assert settings.watch_debounce_seconds == 2.5


def test_leader_election_defaults_and_overrides():
    d = Settings.from_env({})
    assert d.leader_election_enabled is True
    assert d.leader_lease_name == "kaos-sync-leader"
    assert d.leader_lease_duration_seconds == 15.0
    assert d.leader_renew_deadline_seconds == 10.0
    assert d.leader_retry_period_seconds == 2.0
    settings = Settings.from_env(
        {
            "KAOS_SYNC_LEADER_ELECTION_ENABLED": "false",
            "KAOS_SYNC_LEADER_LEASE_NAME": "custom-lease",
            "KAOS_SYNC_LEADER_NAMESPACE": "other-ns",
            "KAOS_SYNC_LEADER_IDENTITY": "pod-7",
            "KAOS_SYNC_LEADER_LEASE_DURATION_SECONDS": "30",
            "KAOS_SYNC_LEADER_RENEW_DEADLINE_SECONDS": "20",
            "KAOS_SYNC_LEADER_RETRY_PERIOD_SECONDS": "5",
        }
    )
    assert settings.leader_election_enabled is False
    assert settings.leader_lease_name == "custom-lease"
    assert settings.leader_namespace == "other-ns"
    assert settings.leader_identity == "pod-7"
    assert settings.leader_lease_duration_seconds == 30.0
    assert settings.leader_renew_deadline_seconds == 20.0
    assert settings.leader_retry_period_seconds == 5.0


def test_leader_namespace_falls_back_to_pod_namespace():
    assert Settings.from_env({"POD_NAMESPACE": "team-a"}).leader_namespace == "team-a"


def test_leader_identity_falls_back_to_pod_name():
    assert Settings.from_env({"POD_NAME": "sync-0"}).leader_identity == "sync-0"
