"""Pure projection of KAOS resources into desired AIB records.

This module contains no I/O. It translates KAOS ``Agent`` and ``MCPServer`` resources
into the desired Agentic Identity Broker (AIB) state using a stable bootstrap encoding:

* Each ``MCPServer`` ``<ns>/<name>`` becomes a synthetic AIB service whose ``client_id``
  is ``kaos-mcpserver-<ns>-<name>`` and which exposes a single ``call`` scope.
* Each requested edge ``Agent -> MCPServer`` becomes an AIB permission set named
  ``kaos:mcpserver:<ns>:<mcp>:call`` that grants the ``call`` scope on that service.
* Each ``Agent`` ``<ns>/<name>`` becomes an AIB *local* agent (created without a
  ``client_id`` so AIB itself mints the actor token) bound to the permission sets for
  its requested edges.

The resource identity an agent is authorized against is ``kaos://mcpserver/<ns>/<name>``,
which the access-check maps back to the synthetic service ``client_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CALL_SCOPE = "call"
MCPSERVER_KIND = "MCPServer"
AGENT_KIND = "Agent"


def service_client_id(namespace: str, name: str) -> str:
    """Synthetic AIB service ``client_id`` for an MCPServer."""
    return f"kaos-mcpserver-{namespace}-{name}"


def permission_set_name(namespace: str, mcp: str) -> str:
    """AIB permission-set name granting ``call`` on an MCPServer."""
    return f"kaos:mcpserver:{namespace}:{mcp}:{CALL_SCOPE}"


def agent_external_id(namespace: str, name: str) -> str:
    """Stable external identity for a KAOS agent in AIB."""
    return f"kaos://agent/{namespace}/{name}"


def mcpserver_resource_uri(namespace: str, name: str) -> str:
    """Resource URI an agent is authorized against for an MCPServer edge."""
    return f"kaos://mcpserver/{namespace}/{name}"


@dataclass(frozen=True)
class DesiredService:
    """A synthetic AIB service projected from an MCPServer."""

    namespace: str
    name: str

    @property
    def client_id(self) -> str:
        return service_client_id(self.namespace, self.name)

    def admin_body(self) -> dict:
        return {
            "display_name": f"KAOS MCPServer {self.namespace}/{self.name} (synthetic)",
            "client_id": self.client_id,
            "client_secret": "synthetic",
            "issuer_uri": f"https://kaos.local/mcpserver/{self.namespace}/{self.name}",
            "discovery": {"enable_discovery": False},
            "endpoints": {
                "token_endpoint": "https://kaos.local/t",
                "authorize_endpoint": "https://kaos.local/a",
            },
            "scopes": [{"scope_value": CALL_SCOPE, "description": "Invoke the MCP server"}],
        }


@dataclass(frozen=True)
class DesiredPermissionSet:
    """An AIB permission set granting ``call`` on one synthetic service."""

    namespace: str
    mcp: str

    @property
    def name(self) -> str:
        return permission_set_name(self.namespace, self.mcp)

    @property
    def service_client_id(self) -> str:
        return service_client_id(self.namespace, self.mcp)

    def admin_body(self, service_id: str) -> dict:
        return {
            "name": self.name,
            "description": f"call {self.namespace}/{self.mcp}",
            "service_scopes": [
                {
                    "service_id": service_id,
                    "scopes": [CALL_SCOPE],
                    "requirement_type": "mandatory",
                }
            ],
        }


@dataclass(frozen=True)
class DesiredAgent:
    """An AIB local agent projected from a KAOS Agent and its requested edges."""

    namespace: str
    name: str
    permission_set_names: tuple[str, ...]
    granted_resources: tuple[str, ...]

    @property
    def external_id(self) -> str:
        return agent_external_id(self.namespace, self.name)

    def admin_body(self, permission_set_ids: list[str]) -> dict:
        return {
            "display_name": self.external_id,
            "description": f"KAOS agent {self.namespace}/{self.name}",
            "permission_sets": [
                {"permission_set_id": pid, "requirement_type": "mandatory"}
                for pid in permission_set_ids
            ],
        }


@dataclass
class DesiredState:
    """The full desired AIB state projected from a set of KAOS resources."""

    services: list[DesiredService] = field(default_factory=list)
    permission_sets: list[DesiredPermissionSet] = field(default_factory=list)
    agents: list[DesiredAgent] = field(default_factory=list)


def _meta(resource: dict) -> tuple[str, str]:
    md = resource.get("metadata", {})
    return md.get("namespace", "default"), md.get("name", "")


def project(resources: list[dict]) -> DesiredState:
    """Project a list of KAOS resources into the desired AIB state.

    Only agents with at least one requested MCPServer edge are projected; an agent with
    no edges has nothing to authorize and is skipped. Services and permission sets are
    derived from the union of declared MCPServers and the edges agents request, so an
    edge to an MCPServer that has no standalone resource still yields a service.
    """
    state = DesiredState()

    services: dict[tuple[str, str], DesiredService] = {}
    permission_sets: dict[tuple[str, str], DesiredPermissionSet] = {}

    def ensure_service(ns: str, name: str) -> None:
        key = (ns, name)
        if key not in services:
            services[key] = DesiredService(namespace=ns, name=name)

    for resource in resources:
        if resource.get("kind") == MCPSERVER_KIND:
            ns, name = _meta(resource)
            if name:
                ensure_service(ns, name)

    for resource in resources:
        if resource.get("kind") != AGENT_KIND:
            continue
        ns, name = _meta(resource)
        if not name:
            continue
        spec = resource.get("spec") or {}
        ps_names: list[str] = []
        granted: list[str] = []
        for mcp in spec.get("mcpServers") or []:
            ensure_service(ns, mcp)
            key = (ns, mcp)
            if key not in permission_sets:
                permission_sets[key] = DesiredPermissionSet(namespace=ns, mcp=mcp)
            ps_names.append(permission_sets[key].name)
            granted.append(mcpserver_resource_uri(ns, mcp))
        if not ps_names:
            continue
        state.agents.append(
            DesiredAgent(
                namespace=ns,
                name=name,
                permission_set_names=tuple(ps_names),
                granted_resources=tuple(granted),
            )
        )

    state.services = list(services.values())
    state.permission_sets = list(permission_sets.values())
    return state
