"""Unit tests for the Scope value object and its Mem0 owner mapping."""

import pytest

from kaos_memory.stores import SHARED_OWNER, Scope, ScopeLevel


def test_private_maps_to_agent_id():
    scope = Scope(level=ScopeLevel.PRIVATE, agent_client_id="agent-a")
    assert scope.owner_kwargs() == {"agent_id": "agent-a"}
    assert scope.search_filters() == {"agent_id": "agent-a"}


def test_user_maps_to_user_id():
    scope = Scope(level=ScopeLevel.USER, principal="alice")
    assert scope.owner_kwargs() == {"user_id": "alice"}


def test_session_maps_to_run_id():
    scope = Scope(level=ScopeLevel.SESSION, session_id="run-1")
    assert scope.owner_kwargs() == {"run_id": "run-1"}


def test_shared_maps_to_reserved_owner_not_empty():
    scope = Scope(level=ScopeLevel.SHARED)
    kwargs = scope.owner_kwargs()
    # Never an empty filter: Mem0 2.x rejects owner-less searches.
    assert kwargs == {"agent_id": SHARED_OWNER}
    assert kwargs


def test_shared_owner_distinct_from_any_private_agent():
    private = Scope(level=ScopeLevel.PRIVATE, agent_client_id="agent-a").owner_kwargs()
    shared = Scope(level=ScopeLevel.SHARED).owner_kwargs()
    # Both use agent_id but the shared sentinel cannot collide with a real agent id.
    assert private["agent_id"] != shared["agent_id"]


def test_each_scope_yields_exactly_one_owner_key():
    for scope in (
        Scope(level=ScopeLevel.PRIVATE, agent_client_id="a"),
        Scope(level=ScopeLevel.USER, principal="p"),
        Scope(level=ScopeLevel.SESSION, session_id="s"),
        Scope(level=ScopeLevel.SHARED),
    ):
        assert len(scope.owner_kwargs()) == 1


def test_incomplete_scope_is_representable_but_raises_on_mapping():
    # Enforcement is a later phase; an under-specified scope can be constructed...
    scope = Scope(level=ScopeLevel.PRIVATE)
    assert not scope.is_complete()
    # ...but mapping it never silently widens to another owner.
    with pytest.raises(ValueError):
        scope.owner_kwargs()


def test_empty_string_owner_is_treated_as_unset():
    scope = Scope(level=ScopeLevel.USER, principal="   ")
    assert scope.principal is None
    assert not scope.is_complete()


def test_complete_flags():
    assert Scope(level=ScopeLevel.SHARED).is_complete()
    assert Scope(level=ScopeLevel.USER, principal="p").is_complete()
    assert not Scope(level=ScopeLevel.SESSION).is_complete()
