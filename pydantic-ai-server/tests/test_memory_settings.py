"""Memory scope policy settings parsing and validation."""

import pytest
from pydantic import ValidationError

from pais.serverutils import AgentServerSettings


def test_read_scope_defaults_follow_home_scope():
    settings = AgentServerSettings(agent_name="test", memory_scope="user")

    assert settings.memory_default_read_scope == "user"
    assert settings.memory_read_scopes == "user"


def test_read_scopes_parse_from_environment(monkeypatch):
    monkeypatch.setenv("MEMORY_SCOPE", "agent")
    monkeypatch.setenv("MEMORY_DEFAULT_READ_SCOPE", "user")
    monkeypatch.setenv("MEMORY_READ_SCOPES", "agent, user,group")

    settings = AgentServerSettings(agent_name="test")

    assert settings.memory_scope == "agent"
    assert settings.memory_default_read_scope == "user"
    assert settings.memory_read_scopes == "agent,user,group"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("memory_scope", "tenant"),
        ("memory_default_read_scope", "tenant"),
        ("memory_read_scopes", "session,tenant"),
        ("memory_read_scopes", "session,,agent"),
    ],
)
def test_unknown_or_empty_scope_values_fail_closed(field, value):
    with pytest.raises(ValidationError):
        AgentServerSettings(agent_name="test", **{field: value})


def test_default_read_scope_must_be_entitled():
    with pytest.raises(ValidationError, match="must be included"):
        AgentServerSettings(
            agent_name="test",
            memory_default_read_scope="user",
            memory_read_scopes="agent,group",
        )
