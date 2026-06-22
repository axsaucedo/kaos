"""Pure projection of KAOS resources into desired AIB records.

This module contains no I/O. It translates KAOS ``Agent``, ``MCPServer`` and ``ModelAPI``
resources into the desired Agentic Identity Broker (AIB) state using a stable bootstrap
encoding shared across the two edge kinds an agent can request (an MCP server it may call,
and the model API it is bound to):

* Each edge target ``<ns>/<name>`` of kind ``<slug>`` becomes a synthetic AIB service whose
  ``client_id`` is ``kaos-<slug>-<ns>-<name>`` and which exposes a single ``call`` scope.
* Each requested edge ``Agent -> target`` becomes an AIB permission set named
  ``kaos:<slug>:<ns>:<name>:call`` that grants the ``call`` scope on that service.
* Each ``Agent`` ``<ns>/<name>`` becomes an AIB *local* agent (created without a
  ``client_id`` so AIB itself mints the actor token) bound to the permission sets for
  its requested edges.

The resource identity an agent is authorized against is ``kaos://<slug>/<ns>/<name>``,
which the access-check maps back to the synthetic service ``client_id``. ``<slug>`` is
``mcpserver`` for MCP server edges and ``modelapi`` for the model API edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CALL_SCOPE = "call"
MCPSERVER_KIND = "MCPServer"
MODELAPI_KIND = "ModelAPI"
AGENT_KIND = "Agent"


@dataclass(frozen=True)
class EdgeKind:
    """An edge target kind and the vocabulary used to encode it into AIB records."""

    slug: str  # identifier segment, e.g. "mcpserver" / "modelapi"
    resource_kind: str  # KAOS resource kind, e.g. "MCPServer" / "ModelAPI"
    display_label: str  # human label used in display names, e.g. "MCPServer"
    scope_description: str  # description attached to the synthetic ``call`` scope


MCPSERVER = EdgeKind(
    slug="mcpserver",
    resource_kind=MCPSERVER_KIND,
    display_label="MCPServer",
    scope_description="Invoke the MCP server",
)
MODELAPI = EdgeKind(
    slug="modelapi",
    resource_kind=MODELAPI_KIND,
    display_label="ModelAPI",
    scope_description="Invoke the model API",
)


def edge_service_client_id(kind: EdgeKind, namespace: str, name: str) -> str:
    """Synthetic AIB service ``client_id`` for an edge target."""
    return f"kaos-{kind.slug}-{namespace}-{name}"


def edge_permission_set_name(kind: EdgeKind, namespace: str, name: str) -> str:
    """AIB permission-set name granting ``call`` on an edge target."""
    return f"kaos:{kind.slug}:{namespace}:{name}:{CALL_SCOPE}"


def edge_resource_uri(kind: EdgeKind, namespace: str, name: str) -> str:
    """Resource URI an agent is authorized against for an edge target."""
    return f"kaos://{kind.slug}/{namespace}/{name}"


def service_client_id(namespace: str, name: str) -> str:
    """Synthetic AIB service ``client_id`` for an MCPServer (stable public helper)."""
    return edge_service_client_id(MCPSERVER, namespace, name)


def permission_set_name(namespace: str, mcp: str) -> str:
    """AIB permission-set name granting ``call`` on an MCPServer (stable public helper)."""
    return edge_permission_set_name(MCPSERVER, namespace, mcp)


def agent_external_id(namespace: str, name: str) -> str:
    """Stable external identity for a KAOS agent in AIB."""
    return f"kaos://agent/{namespace}/{name}"


def mcpserver_resource_uri(namespace: str, name: str) -> str:
    """Resource URI an agent is authorized against for an MCPServer edge."""
    return edge_resource_uri(MCPSERVER, namespace, name)


def modelapi_resource_uri(namespace: str, name: str) -> str:
    """Resource URI an agent is authorized against for a ModelAPI edge."""
    return edge_resource_uri(MODELAPI, namespace, name)


@dataclass(frozen=True)
class DesiredService:
    """A synthetic AIB service projected from an edge target (MCPServer or ModelAPI)."""

    namespace: str
    name: str
    kind: EdgeKind = MCPSERVER

    @property
    def client_id(self) -> str:
        return edge_service_client_id(self.kind, self.namespace, self.name)

    def admin_body(self) -> dict:
        label = self.kind.display_label
        return {
            "display_name": f"KAOS {label} {self.namespace}/{self.name} (synthetic)",
            "client_id": self.client_id,
            "client_secret": "synthetic",
            "issuer_uri": f"https://kaos.local/{self.kind.slug}/{self.namespace}/{self.name}",
            "discovery": {"enable_discovery": False},
            "endpoints": {
                "token_endpoint": "https://kaos.local/t",
                "authorize_endpoint": "https://kaos.local/a",
            },
            "scopes": [{"scope_value": CALL_SCOPE, "description": self.kind.scope_description}],
        }


@dataclass(frozen=True)
class DesiredPermissionSet:
    """An AIB permission set granting ``call`` on one synthetic service."""

    namespace: str
    target: str
    kind: EdgeKind = MCPSERVER

    @property
    def name(self) -> str:
        return edge_permission_set_name(self.kind, self.namespace, self.target)

    @property
    def service_client_id(self) -> str:
        return edge_service_client_id(self.kind, self.namespace, self.target)

    def admin_body(self, service_id: str) -> dict:
        return {
            "name": self.name,
            "description": f"call {self.namespace}/{self.target}",
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

    Both MCP server edges (``spec.mcpServers``) and the model API edge (``spec.modelAPI``)
    are projected, so an agent is authorized against every external dependency it declares.
    Only agents with at least one edge are projected; an agent with no edges has nothing to
    authorize and is skipped. Services and permission sets are derived from the union of
    declared MCPServer/ModelAPI resources and the edges agents request, so an edge to a
    target that has no standalone resource still yields a service.
    """
    state = DesiredState()

    services: dict[tuple[str, str, str], DesiredService] = {}
    permission_sets: dict[tuple[str, str, str], DesiredPermissionSet] = {}

    def ensure_service(kind: EdgeKind, ns: str, name: str) -> None:
        key = (kind.slug, ns, name)
        if key not in services:
            services[key] = DesiredService(namespace=ns, name=name, kind=kind)

    def ensure_permission_set(kind: EdgeKind, ns: str, name: str) -> DesiredPermissionSet:
        key = (kind.slug, ns, name)
        if key not in permission_sets:
            permission_sets[key] = DesiredPermissionSet(namespace=ns, target=name, kind=kind)
        return permission_sets[key]

    declared_kinds = {MCPSERVER.resource_kind: MCPSERVER, MODELAPI.resource_kind: MODELAPI}
    for resource in resources:
        kind = declared_kinds.get(resource.get("kind", ""))
        if kind is None:
            continue
        ns, name = _meta(resource)
        if name:
            ensure_service(kind, ns, name)

    for resource in resources:
        if resource.get("kind") != AGENT_KIND:
            continue
        ns, name = _meta(resource)
        if not name:
            continue
        spec = resource.get("spec") or {}
        ps_names: list[str] = []
        granted: list[str] = []

        def add_edge(kind: EdgeKind, target: str) -> None:
            ensure_service(kind, ns, target)
            ps = ensure_permission_set(kind, ns, target)
            ps_names.append(ps.name)
            granted.append(edge_resource_uri(kind, ns, target))

        for mcp in spec.get("mcpServers") or []:
            add_edge(MCPSERVER, mcp)
        model_api = spec.get("modelAPI")
        if model_api:
            add_edge(MODELAPI, model_api)

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
