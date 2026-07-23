"""Tests for server-side scope derivation.

The request scope must be built from the authenticated request context and the
agent's verifiable identity carried on ``AgentDeps`` — never from model- or
tool-supplied arguments. These tests pin that derivation and confirm the helper
exposes no way for request content to influence the scope.
"""

import inspect

import kaos_identity
import pytest

from pais.memory import (
    MemoryAttribution,
    MemoryScope,
    ScopeLevel,
    attribution_from_deps,
    scope_from_deps,
)
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
        scope = scope_from_deps(deps, level=ScopeLevel.AGENT, agent_identity="stable-agent-id")
        assert scope.agent_client_id == "stable-agent-id"

    def test_accepts_string_level(self):
        deps = _deps(principal="bob")
        scope = scope_from_deps(deps, level="session")
        assert scope.level is ScopeLevel.SESSION

    def test_missing_security_context_yields_unset_owner_fields(self):
        deps = AgentDeps(session_id="sess-9", security_context=None)
        scope = scope_from_deps(deps, level=ScopeLevel.STORE)
        assert scope.principal is None
        assert scope.agent_client_id is None
        assert scope.session_id == "sess-9"

    def test_agent_scope_without_identity_fails_closed(self):
        # An agent scope with no identity would collapse every identity-less
        # agent onto one empty owner; refuse rather than cross-contaminate.
        deps = AgentDeps(session_id="sess-1", security_context=None)
        with pytest.raises(ValueError):
            scope_from_deps(deps, level=ScopeLevel.AGENT)

    def test_agent_scope_uses_actor_when_no_operator_identity(self):
        deps = _deps(actor="agent-actor")
        scope = scope_from_deps(deps, level=ScopeLevel.AGENT)
        assert scope.agent_client_id == "agent-actor"

    def test_agent_scope_is_pool_without_principal(self, monkeypatch):
        monkeypatch.setenv("MEMORY_REQUIRE_PRINCIPAL", "true")
        deps = _deps(actor="agent-actor")
        scope = scope_from_deps(deps, level=ScopeLevel.AGENT)
        assert scope.search_filters() == {"agent_id": "agent-actor"}

    def test_agent_scope_with_principal_uses_agent_and_user_partition(self, monkeypatch):
        monkeypatch.setenv("MEMORY_REQUIRE_PRINCIPAL", "true")
        scope = scope_from_deps(
            _deps(principal="alice", actor="agent-actor"),
            level=ScopeLevel.AGENT,
        )
        assert scope.agent_client_id == "agent-actor"
        assert scope.principal == "alice"
        assert scope.search_filters() == {"user_id": "alice", "agent_id": "agent-actor"}

    def test_autonomous_principal_uses_uniform_required_partition(self, monkeypatch):
        monkeypatch.setenv("MEMORY_REQUIRE_PRINCIPAL", "true")
        identity = "kaos://agent/default/researcher"
        with kaos_identity.autonomous_identity_context("agent-token", identity):
            deps = AgentDeps(
                session_id="loop-1",
                security_context=kaos_identity.security_context(),
            )
            scope = scope_from_deps(
                deps,
                level=ScopeLevel.AGENT,
                agent_identity=identity,
            )

        assert scope.agent_client_id == identity
        assert scope.principal == identity

    def test_write_attribution_keeps_every_verified_contributor(self):
        attribution = attribution_from_deps(_deps(principal="alice", actor="agent-actor"))
        assert isinstance(attribution, MemoryAttribution)
        assert attribution.write_kwargs() == {
            "user_id": "alice",
            "agent_id": "agent-actor",
            "metadata": {"kaos_run": "sess-1"},
        }

    def test_write_attribution_requires_principal_from_posture(self, monkeypatch):
        monkeypatch.setenv("MEMORY_REQUIRE_PRINCIPAL", "true")
        with pytest.raises(ValueError, match="authenticated principal"):
            attribution_from_deps(_deps(actor="agent-actor"))

    def test_write_attribution_requires_agent_identity_from_posture(self, monkeypatch):
        monkeypatch.setenv("MEMORY_REQUIRE_AGENT_IDENTITY", "true")
        with pytest.raises(ValueError, match="stable agent identity"):
            attribution_from_deps(_deps(principal="alice"))

    def test_helper_takes_no_scope_argument(self):
        # The derivation must not accept caller/model-supplied scope: there is no
        # parameter through which request content could set principal, owner, or level.
        params = set(inspect.signature(scope_from_deps).parameters)
        assert params == {"deps", "level", "agent_identity"}

    def test_model_supplied_fields_on_deps_are_ignored(self):
        # Even if extra attributes are attached, only the known identity fields are read.
        deps = _deps(principal="alice", actor="agent-1")
        setattr(deps, "scope", "store")  # would-be injected override
        setattr(deps, "principal", "attacker")
        scope = scope_from_deps(deps, level=ScopeLevel.AGENT)
        assert scope.level is ScopeLevel.AGENT
        assert scope.principal == "alice"
