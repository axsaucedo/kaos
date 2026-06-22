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
AGENT_SLUG = "agent"


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


def _logical_path(namespace: str, name: str, security_id: str = "") -> str:
    """Path segment of a logical identity: the explicit id when set, else ``<ns>/<name>``."""
    return security_id if security_id else f"{namespace}/{name}"


def resolve_logical_id(slug: str, namespace: str, name: str, security_id: str = "") -> str:
    """Logical identity URI for a resource.

    Mirrors the operator's resolver: ``kaos://<slug>/<id>`` when an explicit
    ``spec.security.id`` is set (namespace-independent), otherwise the
    namespace-scoped default ``kaos://<slug>/<ns>/<name>``.
    """
    return f"kaos://{slug}/{_logical_path(namespace, name, security_id)}"


def edge_service_client_id(kind: EdgeKind, namespace: str, name: str, security_id: str = "") -> str:
    """Synthetic AIB service ``client_id`` for an edge target."""
    segment = _logical_path(namespace, name, security_id).replace("/", "-")
    return f"kaos-{kind.slug}-{segment}"


def edge_permission_set_name(
    kind: EdgeKind, namespace: str, name: str, security_id: str = ""
) -> str:
    """AIB permission-set name granting ``call`` on an edge target."""
    segment = _logical_path(namespace, name, security_id).replace("/", ":")
    return f"kaos:{kind.slug}:{segment}:{CALL_SCOPE}"


def edge_resource_uri(kind: EdgeKind, namespace: str, name: str, security_id: str = "") -> str:
    """Resource URI an agent is authorized against for an edge target."""
    return resolve_logical_id(kind.slug, namespace, name, security_id)


def service_client_id(namespace: str, name: str) -> str:
    """Synthetic AIB service ``client_id`` for an MCPServer (stable public helper)."""
    return edge_service_client_id(MCPSERVER, namespace, name)


def permission_set_name(namespace: str, mcp: str) -> str:
    """AIB permission-set name granting ``call`` on an MCPServer (stable public helper)."""
    return edge_permission_set_name(MCPSERVER, namespace, mcp)


def agent_external_id(namespace: str, name: str, security_id: str = "") -> str:
    """Stable external identity for a KAOS agent in AIB."""
    return resolve_logical_id(AGENT_SLUG, namespace, name, security_id)


def mcpserver_resource_uri(namespace: str, name: str) -> str:
    """Resource URI an agent is authorized against for an MCPServer edge."""
    return edge_resource_uri(MCPSERVER, namespace, name)


def modelapi_resource_uri(namespace: str, name: str) -> str:
    """Resource URI an agent is authorized against for a ModelAPI edge."""
    return edge_resource_uri(MODELAPI, namespace, name)


_AGENT_DISPLAY_PREFIX = "kaos://agent/"
_SERVICE_CLIENT_ID_PREFIXES = (f"kaos-{MCPSERVER.slug}-", f"kaos-{MODELAPI.slug}-")
_PERMISSION_SET_PREFIX = "kaos:"


def is_kaos_service_client_id(client_id: str) -> bool:
    """True if a broker service ``client_id`` was projected by KAOS (safe to prune)."""
    return client_id.startswith(_SERVICE_CLIENT_ID_PREFIXES)


def is_kaos_permission_set_name(name: str) -> bool:
    """True if a broker permission-set ``name`` was projected by KAOS (safe to prune)."""
    return name.startswith(_PERMISSION_SET_PREFIX)


def is_kaos_agent_display_name(display_name: str) -> bool:
    """True if a broker agent ``display_name`` was projected by KAOS (safe to prune)."""
    return display_name.startswith(_AGENT_DISPLAY_PREFIX)


def parse_agent_external_id(external_id: str) -> tuple[str, str] | None:
    """Parse ``kaos://agent/<ns>/<name>`` into ``(namespace, name)`` or ``None``.

    Only the namespace-scoped default form has a namespace/name pair; the
    explicit-id form ``kaos://agent/<id>`` returns ``None`` (use
    :func:`is_valid_agent_external_id` to test ownership of either form).
    """
    if not is_kaos_agent_display_name(external_id):
        return None
    rest = external_id[len(_AGENT_DISPLAY_PREFIX) :]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def is_valid_agent_external_id(external_id: str) -> bool:
    """True if ``external_id`` is a well-formed KAOS agent external id.

    Accepts both the namespace-scoped default (``kaos://agent/<ns>/<name>``) and
    the explicit-id form (``kaos://agent/<id>``) so an explicit-id agent that has
    been deleted is still recognised as KAOS-owned and pruned, rather than being
    treated as malformed and leaked.
    """
    if not is_kaos_agent_display_name(external_id):
        return False
    rest = external_id[len(_AGENT_DISPLAY_PREFIX) :]
    segments = rest.split("/")
    return len(segments) in (1, 2) and all(segments)


@dataclass(frozen=True)
class DesiredService:
    """A synthetic AIB service projected from an edge target (MCPServer or ModelAPI)."""

    namespace: str
    name: str
    kind: EdgeKind = MCPSERVER
    security_id: str = ""

    @property
    def client_id(self) -> str:
        return edge_service_client_id(self.kind, self.namespace, self.name, self.security_id)

    def admin_body(self) -> dict:
        label = self.kind.display_label
        path = _logical_path(self.namespace, self.name, self.security_id)
        return {
            "display_name": f"KAOS {label} {path} (synthetic)",
            "client_id": self.client_id,
            "client_secret": "synthetic",
            "issuer_uri": f"https://kaos.local/{self.kind.slug}/{path}",
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
    security_id: str = ""

    @property
    def name(self) -> str:
        return edge_permission_set_name(self.kind, self.namespace, self.target, self.security_id)

    @property
    def service_client_id(self) -> str:
        return edge_service_client_id(self.kind, self.namespace, self.target, self.security_id)

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
    security_id: str = ""

    @property
    def external_id(self) -> str:
        return agent_external_id(self.namespace, self.name, self.security_id)

    def admin_body(self, permission_set_ids: list[str]) -> dict:
        return {
            "display_name": self.external_id,
            "description": f"KAOS agent {self.namespace}/{self.name}",
            "permission_sets": [
                {"permission_set_id": pid, "requirement_type": "mandatory"}
                for pid in permission_set_ids
            ],
        }


@dataclass(frozen=True)
class IdentityConflict:
    """A resource whose explicit ``spec.security.id`` is already held by an older resource."""

    kind: str  # logical slug: "agent" / "mcpserver" / "modelapi"
    security_id: str
    namespace: str  # the losing resource
    name: str
    holder_namespace: str  # the legitimate (oldest) holder
    holder_name: str


@dataclass
class DesiredState:
    """The full desired AIB state projected from a set of KAOS resources."""

    services: list[DesiredService] = field(default_factory=list)
    permission_sets: list[DesiredPermissionSet] = field(default_factory=list)
    agents: list[DesiredAgent] = field(default_factory=list)
    conflicts: list[IdentityConflict] = field(default_factory=list)


def _resource_identity(resource: dict) -> tuple[str, str, str, str]:
    """Extract ``(namespace, name, security_id, creation_timestamp)`` from a resource.

    ``security_id`` is ``spec.security.id`` (empty when unset) and
    ``creation_timestamp`` is the RFC 3339 ``metadata.creationTimestamp`` used to
    pick the oldest holder of a shared explicit id (lexicographic order on the
    fixed-offset RFC 3339 form matches chronological order).
    """
    md = resource.get("metadata", {})
    ns = md.get("namespace", "default")
    name = md.get("name", "")
    spec = resource.get("spec") or {}
    security = spec.get("security") or {}
    security_id = security.get("id", "") or ""
    creation = md.get("creationTimestamp", "") or ""
    return ns, name, security_id, creation


def _winners_and_conflicts(
    records: list[tuple[str, str, str, str]],
) -> tuple[set[tuple[str, str]], list[tuple[str, str, str, str, str]]]:
    """Resolve shared explicit ids to a single holder.

    ``records`` is a list of ``(namespace, name, security_id, creation)``. Among
    records sharing a non-empty ``security_id``, the oldest by creation (then
    namespace, then name) is the legitimate holder. Returns the set of loser
    ``(namespace, name)`` keys to skip and a list of
    ``(namespace, name, holder_namespace, holder_name, security_id)`` conflicts.
    """
    by_id: dict[str, list[tuple[str, str, str]]] = {}
    for ns, name, sid, creation in records:
        if sid:
            by_id.setdefault(sid, []).append((creation, ns, name))

    losers: set[tuple[str, str]] = set()
    conflicts: list[tuple[str, str, str, str, str]] = []
    for sid, group in by_id.items():
        group.sort()
        _, holder_ns, holder_name = group[0]
        for _, ns, name in group[1:]:
            losers.add((ns, name))
            conflicts.append((ns, name, holder_ns, holder_name, sid))
    return losers, conflicts


def project(resources: list[dict]) -> DesiredState:
    """Project a list of KAOS resources into the desired AIB state.

    Both MCP server edges (``spec.mcpServers``) and the model API edge (``spec.modelAPI``)
    are projected, so an agent is authorized against every external dependency it declares.
    Only agents with at least one edge are projected; an agent with no edges has nothing to
    authorize and is skipped. Services and permission sets are derived from the union of
    declared MCPServer/ModelAPI resources and the edges agents request, so an edge to a
    target that has no standalone resource still yields a service.

    Logical identities honour ``spec.security.id``: a resource with an explicit id is
    projected under ``kaos://<slug>/<id>`` (namespace-independent), and an agent edge to a
    target resolves to that target's identity. When two resources of the same kind declare
    the same explicit id, the oldest is the legitimate holder; the others are skipped and
    recorded in :attr:`DesiredState.conflicts`.
    """
    state = DesiredState()

    services: dict[str, DesiredService] = {}
    permission_sets: dict[str, DesiredPermissionSet] = {}

    def ensure_service(kind: EdgeKind, ns: str, name: str, security_id: str) -> None:
        svc = DesiredService(namespace=ns, name=name, kind=kind, security_id=security_id)
        services.setdefault(svc.client_id, svc)

    def ensure_permission_set(
        kind: EdgeKind, ns: str, name: str, security_id: str
    ) -> DesiredPermissionSet:
        ps = DesiredPermissionSet(namespace=ns, target=name, kind=kind, security_id=security_id)
        return permission_sets.setdefault(ps.name, ps)

    # Pass 1: index declared edge targets, resolve their explicit ids and dedup.
    declared_kinds = {MCPSERVER.resource_kind: MCPSERVER, MODELAPI.resource_kind: MODELAPI}
    target_security: dict[tuple[str, str, str], str] = {}
    per_kind_records: dict[str, list[tuple[str, str, str, str]]] = {
        MCPSERVER.slug: [],
        MODELAPI.slug: [],
    }
    declared: list[tuple[EdgeKind, str, str, str]] = []
    for resource in resources:
        kind = declared_kinds.get(resource.get("kind", ""))
        if kind is None:
            continue
        ns, name, sid, creation = _resource_identity(resource)
        if not name:
            continue
        target_security[(kind.slug, ns, name)] = sid
        per_kind_records[kind.slug].append((ns, name, sid, creation))
        declared.append((kind, ns, name, sid))

    edge_losers: dict[str, set[tuple[str, str]]] = {}
    for slug, records in per_kind_records.items():
        losers, conflicts = _winners_and_conflicts(records)
        edge_losers[slug] = losers
        for ns, name, holder_ns, holder_name, sid in conflicts:
            state.conflicts.append(IdentityConflict(slug, sid, ns, name, holder_ns, holder_name))

    for kind, ns, name, sid in declared:
        if (ns, name) in edge_losers[kind.slug]:
            continue
        ensure_service(kind, ns, name, sid)

    # Pass 2: agents -- dedup by explicit id, then project edges and grants.
    agent_records: list[tuple[str, str, str, str]] = []
    for resource in resources:
        if resource.get("kind") != AGENT_KIND:
            continue
        ns, name, sid, creation = _resource_identity(resource)
        if name:
            agent_records.append((ns, name, sid, creation))
    agent_losers, agent_conflicts = _winners_and_conflicts(agent_records)
    for ns, name, holder_ns, holder_name, sid in agent_conflicts:
        state.conflicts.append(IdentityConflict(AGENT_SLUG, sid, ns, name, holder_ns, holder_name))

    for resource in resources:
        if resource.get("kind") != AGENT_KIND:
            continue
        ns, name, agent_sid, _creation = _resource_identity(resource)
        if not name or (ns, name) in agent_losers:
            continue
        spec = resource.get("spec") or {}
        ps_names: list[str] = []
        granted: list[str] = []

        def add_edge(kind: EdgeKind, target: str) -> None:
            tsid = target_security.get((kind.slug, ns, target), "")
            ensure_service(kind, ns, target, tsid)
            ps = ensure_permission_set(kind, ns, target, tsid)
            ps_names.append(ps.name)
            granted.append(edge_resource_uri(kind, ns, target, tsid))

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
                security_id=agent_sid,
            )
        )

    state.services = list(services.values())
    state.permission_sets = list(permission_sets.values())
    return state
