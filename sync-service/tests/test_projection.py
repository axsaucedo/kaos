"""Tests for the pure KAOS -> AIB projection."""

from __future__ import annotations

from kaos_sync.projection import (
    DesiredState,
    agent_external_id,
    mcpserver_resource_uri,
    permission_set_name,
    project,
    service_client_id,
)


def _mcpserver(name: str, namespace: str = "demo") -> dict:
    return {
        "kind": "MCPServer",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"runtime": "python-string"},
    }


def _agent(name: str, mcp_servers: list[str], namespace: str = "demo") -> dict:
    return {
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"modelAPI": "gpt", "model": "gpt-4", "mcpServers": mcp_servers},
    }


def test_encoding_conventions():
    assert service_client_id("demo", "github") == "kaos-mcpserver-demo-github"
    assert permission_set_name("demo", "github") == "kaos:mcpserver:demo:github:call"
    assert agent_external_id("demo", "researcher") == "kaos://agent/demo/researcher"
    assert mcpserver_resource_uri("demo", "github") == "kaos://mcpserver/demo/github"


def test_project_full_graph():
    state = project(
        [
            _mcpserver("github"),
            _mcpserver("slack"),
            _agent("researcher", ["github"]),
        ]
    )

    # Both declared MCPServers become services even if only one is granted.
    assert {s.client_id for s in state.services} == {
        "kaos-mcpserver-demo-github",
        "kaos-mcpserver-demo-slack",
    }
    # Only the requested edge yields a permission set.
    assert [ps.name for ps in state.permission_sets] == ["kaos:mcpserver:demo:github:call"]

    assert len(state.agents) == 1
    agent = state.agents[0]
    assert agent.external_id == "kaos://agent/demo/researcher"
    assert agent.permission_set_names == ("kaos:mcpserver:demo:github:call",)
    assert agent.granted_resources == ("kaos://mcpserver/demo/github",)


def test_agent_without_edges_is_skipped():
    state = project([_mcpserver("github"), _agent("idle", [])])
    assert state.agents == []
    # The standalone MCPServer is still projected as a service.
    assert [s.client_id for s in state.services] == ["kaos-mcpserver-demo-github"]


def test_edge_to_undeclared_mcpserver_still_yields_service():
    # Agent references an MCPServer that has no standalone resource in the input.
    state = project([_agent("researcher", ["ghost"])])
    assert [s.client_id for s in state.services] == ["kaos-mcpserver-demo-ghost"]
    assert [ps.name for ps in state.permission_sets] == ["kaos:mcpserver:demo:ghost:call"]
    assert state.agents[0].granted_resources == ("kaos://mcpserver/demo/ghost",)


def test_projection_is_idempotent_and_deduplicates():
    resources = [
        _mcpserver("github"),
        _agent("a", ["github"]),
        _agent("b", ["github"]),
    ]
    first = project(resources)
    second = project(resources)

    # Shared service/permission set are not duplicated across two agents.
    assert len(first.services) == 1
    assert len(first.permission_sets) == 1
    assert len(first.agents) == 2

    # Deterministic output: re-projecting the same input yields equal state.
    assert _as_tuple(first) == _as_tuple(second)


def test_admin_bodies_shape():
    state = project([_mcpserver("github"), _agent("researcher", ["github"])])

    svc_body = state.services[0].admin_body()
    assert svc_body["client_id"] == "kaos-mcpserver-demo-github"
    assert svc_body["scopes"] == [{"scope_value": "call", "description": "Invoke the MCP server"}]

    ps_body = state.permission_sets[0].admin_body(service_id="svc-123")
    assert ps_body["service_scopes"][0]["service_id"] == "svc-123"
    assert ps_body["service_scopes"][0]["scopes"] == ["call"]

    # Local agent body carries no client_id so AIB mints the actor token locally.
    agent_body = state.agents[0].admin_body(permission_set_ids=["ps-1"])
    assert "client_id" not in agent_body
    assert agent_body["permission_sets"] == [
        {"permission_set_id": "ps-1", "requirement_type": "mandatory"}
    ]


def _as_tuple(state: DesiredState):
    return (
        tuple(sorted(s.client_id for s in state.services)),
        tuple(sorted(ps.name for ps in state.permission_sets)),
        tuple(sorted(a.external_id for a in state.agents)),
    )
