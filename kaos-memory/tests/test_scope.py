"""Unit tests for the Scope value object and its Mem0 attribution mapping."""

import pytest

from kaos_memory.stores import Scope, ScopeLevel, scope_key


def test_agent_maps_to_agent_id():
    scope = Scope(level=ScopeLevel.AGENT, agent_client_id="agent-a")
    assert scope.owner_kwargs() == {"agent_id": "agent-a"}
    assert scope.search_filters() == {"agent_id": "agent-a"}


def test_required_agent_scope_is_incomplete_without_user():
    scope = Scope(
        level=ScopeLevel.AGENT,
        agent_client_id="agent-a",
        user_scoping_required=True,
    )
    assert scope.is_complete() is False


def test_user_maps_to_user_id():
    scope = Scope(level=ScopeLevel.USER, principal="alice")
    assert scope.owner_kwargs() == {"user_id": "alice"}
    assert scope.search_filters() == {"user_id": "alice"}


def test_session_maps_to_run_id():
    scope = Scope(level=ScopeLevel.SESSION, session_id="run-1")
    assert scope.owner_kwargs() == {"run_id": "run-1"}
    assert scope.search_filters() == {"user_id": "*", "kaos_run": "run-1"}


def test_group_search_uses_wildcard_and_store_group():
    scope = Scope(level=ScopeLevel.GROUP)
    assert scope.search_filters("team-a") == {"user_id": "*", "kaos_group": "team-a"}


def test_group_search_requires_store_group():
    with pytest.raises(ValueError, match="store group"):
        Scope(level=ScopeLevel.GROUP).search_filters()


def test_entity_scopes_yield_exactly_one_owner_key():
    for scope in (
        Scope(level=ScopeLevel.AGENT, agent_client_id="a"),
        Scope(level=ScopeLevel.USER, principal="p"),
        Scope(level=ScopeLevel.SESSION, session_id="s"),
    ):
        assert len(scope.owner_kwargs()) == 1


def test_group_has_no_synthetic_entity_owner():
    with pytest.raises(ValueError, match="no Mem0 entity owner"):
        Scope(level=ScopeLevel.GROUP).owner_kwargs()


def test_write_kwargs_carry_all_known_attribution():
    scope = Scope(
        level=ScopeLevel.GROUP,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )
    assert scope.write_kwargs("team-a") == {
        "user_id": "alice",
        "agent_id": "agent-a",
        "metadata": {"kaos_run": "run-1", "kaos_group": "team-a"},
    }


def test_write_kwargs_omit_unknown_attribution():
    scope = Scope(level=ScopeLevel.AGENT, agent_client_id="agent-a")
    assert scope.write_kwargs() == {"agent_id": "agent-a"}


def test_write_requires_an_entity_contributor():
    with pytest.raises(ValueError, match="principal or agent_client_id"):
        Scope(level=ScopeLevel.GROUP, session_id="run-1").write_kwargs("team-a")


@pytest.mark.parametrize(
    ("scope", "group", "expected"),
    [
        (
            Scope(level=ScopeLevel.USER, principal="alice", session_id="run-1"),
            None,
            "run:run-1",
        ),
        (
            Scope(level=ScopeLevel.AGENT, agent_client_id="agent-a", session_id="run-1"),
            None,
            "run:run-1",
        ),
        (
            Scope(level=ScopeLevel.SESSION, session_id="run-1"),
            None,
            "run:run-1",
        ),
        (
            Scope(level=ScopeLevel.GROUP, session_id="run-1"),
            "team-a",
            "kaos_group:team-a|run:run-1",
        ),
    ],
)
def test_scope_key_uses_session_with_optional_store_boundary(scope, group, expected):
    assert scope_key(scope, group) == expected


def test_scope_key_ignores_write_attribution_and_recall_level():
    agent = Scope(
        level=ScopeLevel.AGENT,
        principal="alice",
        agent_client_id="agent-a",
        session_id="run-1",
    )
    group = Scope(level=ScopeLevel.GROUP, session_id="run-1")

    expected = "kaos_group:team-a|run:run-1"
    assert scope_key(agent, "team-a") == expected
    assert scope_key(group, "team-a") == expected


def test_scope_key_requires_session_for_every_level():
    with pytest.raises(ValueError, match="requires session_id"):
        scope_key(Scope(level=ScopeLevel.USER, principal="alice"))


def test_incomplete_scope_is_representable_but_raises_on_mapping():
    # Enforcement is a later phase; an under-specified scope can be constructed...
    scope = Scope(level=ScopeLevel.AGENT)
    assert not scope.is_complete()
    # ...but mapping it never silently widens to another owner.
    with pytest.raises(ValueError):
        scope.owner_kwargs()


def test_empty_string_owner_is_treated_as_unset():
    scope = Scope(level=ScopeLevel.USER, principal="   ")
    assert scope.principal is None
    assert not scope.is_complete()


def test_complete_flags():
    assert Scope(level=ScopeLevel.GROUP).is_complete()
    assert Scope(level=ScopeLevel.USER, principal="p").is_complete()
    assert not Scope(level=ScopeLevel.SESSION).is_complete()
