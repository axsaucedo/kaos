"""Tests for the pure KAOS -> AIB projection."""

from __future__ import annotations

from kaos_sync.projection import (
    DesiredState,
    agent_external_id,
    mcpserver_resource_uri,
    modelapi_resource_uri,
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


def _modelapi(name: str, namespace: str = "demo") -> dict:
    return {
        "kind": "ModelAPI",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"mode": "proxy"},
    }


def _agent(
    name: str,
    mcp_servers: list[str],
    namespace: str = "demo",
    model_api: str | None = "gpt",
) -> dict:
    spec: dict = {"model": "gpt-4", "mcpServers": mcp_servers}
    if model_api is not None:
        spec["modelAPI"] = model_api
    return {
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }


def test_encoding_conventions():
    assert service_client_id("demo", "github") == "kaos-mcpserver-demo-github"
    assert permission_set_name("demo", "github") == "kaos:mcpserver:demo:github:call"
    assert agent_external_id("demo", "researcher") == "kaos://agent/demo/researcher"
    assert mcpserver_resource_uri("demo", "github") == "kaos://mcpserver/demo/github"
    assert modelapi_resource_uri("demo", "gpt") == "kaos://modelapi/demo/gpt"


def test_project_full_graph():
    state = project(
        [
            _mcpserver("github"),
            _mcpserver("slack"),
            _modelapi("gpt"),
            _agent("researcher", ["github"], model_api="gpt"),
        ]
    )

    # Both declared MCPServers and the ModelAPI become services even if only some are granted.
    assert {s.client_id for s in state.services} == {
        "kaos-mcpserver-demo-github",
        "kaos-mcpserver-demo-slack",
        "kaos-modelapi-demo-gpt",
    }
    # The requested MCP edge and the model API edge each yield a permission set.
    assert {ps.name for ps in state.permission_sets} == {
        "kaos:mcpserver:demo:github:call",
        "kaos:modelapi:demo:gpt:call",
    }

    assert len(state.agents) == 1
    agent = state.agents[0]
    assert agent.external_id == "kaos://agent/demo/researcher"
    # MCP edges are projected before the model API edge.
    assert agent.permission_set_names == (
        "kaos:mcpserver:demo:github:call",
        "kaos:modelapi:demo:gpt:call",
    )
    assert agent.granted_resources == (
        "kaos://mcpserver/demo/github",
        "kaos://modelapi/demo/gpt",
    )


def test_model_api_edge_is_projected_without_mcp_servers():
    # An agent with only a model API still gets a modelapi service, permission set and edge.
    state = project([_agent("solo", [], model_api="gpt")])
    assert [s.client_id for s in state.services] == ["kaos-modelapi-demo-gpt"]
    assert [ps.name for ps in state.permission_sets] == ["kaos:modelapi:demo:gpt:call"]
    assert len(state.agents) == 1
    assert state.agents[0].granted_resources == ("kaos://modelapi/demo/gpt",)


def test_agent_without_any_edge_is_skipped():
    # No MCP servers and no model API: nothing to authorize, so the agent is skipped.
    state = project([_mcpserver("github"), _agent("idle", [], model_api=None)])
    assert state.agents == []
    # The standalone MCPServer is still projected as a service.
    assert [s.client_id for s in state.services] == ["kaos-mcpserver-demo-github"]


def test_declared_model_api_yields_service_even_when_ungranted():
    state = project([_modelapi("gpt"), _agent("idle", [], model_api=None)])
    assert [s.client_id for s in state.services] == ["kaos-modelapi-demo-gpt"]
    assert state.permission_sets == []
    assert state.agents == []


def test_edge_to_undeclared_mcpserver_still_yields_service():
    # Agent references an MCPServer that has no standalone resource in the input.
    state = project([_agent("researcher", ["ghost"], model_api=None)])
    assert [s.client_id for s in state.services] == ["kaos-mcpserver-demo-ghost"]
    assert [ps.name for ps in state.permission_sets] == ["kaos:mcpserver:demo:ghost:call"]
    assert state.agents[0].granted_resources == ("kaos://mcpserver/demo/ghost",)


def test_projection_is_idempotent_and_deduplicates():
    resources = [
        _mcpserver("github"),
        _modelapi("gpt"),
        _agent("a", ["github"], model_api="gpt"),
        _agent("b", ["github"], model_api="gpt"),
    ]
    first = project(resources)
    second = project(resources)

    # Shared services/permission sets are not duplicated across two agents.
    assert len(first.services) == 2
    assert len(first.permission_sets) == 2
    assert len(first.agents) == 2

    # Deterministic output: re-projecting the same input yields equal state.
    assert _as_tuple(first) == _as_tuple(second)


def test_admin_bodies_shape():
    state = project([_mcpserver("github"), _agent("researcher", ["github"], model_api=None)])

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


def test_model_api_admin_body_uses_model_api_vocabulary():
    state = project([_modelapi("gpt"), _agent("solo", [], model_api="gpt")])
    svc = next(s for s in state.services if s.client_id == "kaos-modelapi-demo-gpt")
    body = svc.admin_body()
    assert body["display_name"] == "KAOS ModelAPI demo/gpt (synthetic)"
    assert body["scopes"] == [{"scope_value": "call", "description": "Invoke the model API"}]


def _as_tuple(state: DesiredState):
    return (
        tuple(sorted(s.client_id for s in state.services)),
        tuple(sorted(ps.name for ps in state.permission_sets)),
        tuple(sorted(a.external_id for a in state.agents)),
    )
