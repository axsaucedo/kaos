"""Tests for server-side scope derivation.

The request scope must be built from the authenticated request context and the
agent's verifiable identity carried on ``AgentDeps`` — never from model- or
tool-supplied arguments. These tests pin that derivation and confirm the helper
exposes no way for request content to influence the scope.
"""

import inspect

import pytest

from pais.memory import MemoryScope, ScopeLevel, scope_from_deps
from pais.serverutils import AgentDeps


def _deps(**security_context) -> AgentDeps:
    return AgentDeps(
        session_id=security_context.pop("_session_id", "sess-1"),
        security_context=security_context or None,
    )


class TestScopeFromDeps:
    def test_builds_scope_from_request_context_and_identity(self):
        deps = _deps(principal="alice", actor="agent-actor")
        scope = scope_from_deps(deps, level=ScopeLevel.USER)
        assert isinstance(scope, MemoryScope)
        assert scope.level is ScopeLevel.USER
        assert scope.principal == "alice"
        assert scope.agent_client_id == "agent-actor"
        assert scope.session_id == "sess-1"

    def test_operator_agent_identity_overrides_actor(self):
        deps = _deps(principal="alice", actor="actor-token-subject")
        scope = scope_from_deps(deps, level=ScopeLevel.PRIVATE, agent_identity="stable-agent-id")
        assert scope.agent_client_id == "stable-agent-id"

    def test_accepts_string_level(self):
        deps = _deps(principal="bob")
        scope = scope_from_deps(deps, level="session")
        assert scope.level is ScopeLevel.SESSION

    def test_missing_security_context_yields_unset_owner_fields(self):
        deps = AgentDeps(session_id="sess-9", security_context=None)
        scope = scope_from_deps(deps, level=ScopeLevel.SHARED)
        assert scope.principal is None
        assert scope.agent_client_id is None
        assert scope.session_id == "sess-9"

    def test_private_scope_without_identity_fails_closed(self):
        # A private scope with no agent identity would collapse every identity-less
        # agent onto one shared-empty owner; refuse rather than cross-contaminate.
        deps = AgentDeps(session_id="sess-1", security_context=None)
        with pytest.raises(ValueError):
            scope_from_deps(deps, level=ScopeLevel.PRIVATE)

    def test_private_scope_uses_actor_when_no_operator_identity(self):
        deps = _deps(actor="agent-actor")
        scope = scope_from_deps(deps, level=ScopeLevel.PRIVATE)
        assert scope.agent_client_id == "agent-actor"

    def test_helper_takes_no_scope_argument(self):
        # The derivation must not accept caller/model-supplied scope: there is no
        # parameter through which request content could set principal, owner, or level.
        params = set(inspect.signature(scope_from_deps).parameters)
        assert params == {"deps", "level", "agent_identity"}

    def test_model_supplied_fields_on_deps_are_ignored(self):
        # Even if extra attributes are attached, only the known identity fields are read.
        deps = _deps(principal="alice", actor="agent-1")
        setattr(deps, "scope", "shared")  # would-be injected override
        setattr(deps, "principal", "attacker")
        scope = scope_from_deps(deps, level=ScopeLevel.PRIVATE)
        assert scope.level is ScopeLevel.PRIVATE
        assert scope.principal == "alice"
