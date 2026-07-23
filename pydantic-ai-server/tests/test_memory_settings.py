"""Memory scope policy settings parsing and validation."""

import pytest
from pydantic import ValidationError

from pais.serverutils import AgentServerSettings


def test_max_read_scope_defaults_to_session():
    settings = AgentServerSettings(agent_name="test")

    assert settings.memory_max_read_scope == "session"


def test_max_read_scope_parses_from_environment(monkeypatch):
    monkeypatch.setenv("MEMORY_MAX_READ_SCOPE", "user")

    settings = AgentServerSettings(agent_name="test")

    assert settings.memory_max_read_scope == "user"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("memory_max_read_scope", "tenant"),
    ],
)
def test_unknown_or_empty_scope_values_fail_closed(field, value):
    with pytest.raises(ValidationError):
        AgentServerSettings(agent_name="test", **{field: value})
