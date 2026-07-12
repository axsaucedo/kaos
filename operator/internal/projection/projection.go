// Package projection turns KAOS resources into a provider-agnostic authorization
// graph. It is pure (no I/O) so it can be unit tested without a cluster, and the
// same graph feeds both projection sinks: the KAOS policy-data path (grant map
// for OPA) and the broker path (services, permission sets and agents).
//
// Each edge target <ns>/<name> of kind <slug> becomes a synthetic service whose
// client_id is kaos-<slug>-<ns>-<name> exposing a single "call" scope. Each
// requested edge Agent -> target becomes a permission set granting that scope,
// and each Agent becomes a projected agent bound to the permission sets for its
// requested edges. The resource an agent is authorized against is
// kaos://<slug>/<ns>/<name>, which is unique by construction.
package projection

import (
	"fmt"
	"strings"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	// CallScope is the single scope every synthetic edge service exposes.
	CallScope = "call"
	// AgentKind is the KAOS Agent resource kind.
	AgentKind = "Agent"
	// AgentSlug is the logical-id slug for agents.
	AgentSlug = "agent"

	agentDisplayPrefix  = "kaos://agent/"
	permissionSetPrefix = "kaos:"
)

// EdgeKind is an edge target kind and the vocabulary used to encode it into the
// projected authorization graph.
type EdgeKind struct {
	Slug             string // identifier segment, e.g. "mcpserver" / "modelapi"
	ResourceKind     string // KAOS resource kind, e.g. "MCPServer" / "ModelAPI"
	DisplayLabel     string // human label used in display names
	ScopeDescription string // description attached to the synthetic "call" scope
}

// The edge kinds an agent can request. Agent->Agent edges (spec.agentNetwork.access)
// authorize peer A2A delegation on the calling agent's actor identity, the same
// way MCPServer/ModelAPI/MemoryStore edges authorize dependency calls.
var (
	MCPServer   = EdgeKind{Slug: "mcpserver", ResourceKind: "MCPServer", DisplayLabel: "MCPServer", ScopeDescription: "Invoke the MCP server"}
	ModelAPI    = EdgeKind{Slug: "modelapi", ResourceKind: "ModelAPI", DisplayLabel: "ModelAPI", ScopeDescription: "Invoke the model API"}
	MemoryStore = EdgeKind{Slug: "memorystore", ResourceKind: "MemoryStore", DisplayLabel: "MemoryStore", ScopeDescription: "Invoke the memory store"}
	Agent       = EdgeKind{Slug: AgentSlug, ResourceKind: AgentKind, DisplayLabel: "Agent", ScopeDescription: "Invoke the agent (A2A)"}
)

var serviceClientIDPrefixes = []string{"kaos-" + MCPServer.Slug + "-", "kaos-" + ModelAPI.Slug + "-", "kaos-" + MemoryStore.Slug + "-", "kaos-" + Agent.Slug + "-"}

// Resource is the minimal KAOS resource shape the projection needs. The runtime
// converts unstructured CRDs into this; tests construct it directly.
type Resource struct {
	Kind        string
	Namespace   string
	Name        string
	Labels      map[string]string
	MCPServers  []string // spec.mcpServers (Agent only)
	ModelAPI    string   // spec.modelAPI (Agent only)
	MemoryStore string   // spec.config.memory.memoryStore (Agent only)
	Access      []string // spec.agentNetwork.access -- peer agents this agent may call (Agent only)
	Autonomous  bool     // spec.autonomous.goal is non-empty (Agent only)
}

// AccessGrant is the projection input for a namespaced user-plane grant.
type AccessGrant struct {
	Namespace string
	Subjects  []AccessGrantSubject
	Resources []AccessGrantResource
}

type AccessGrantSubject struct {
	Kind string
	Name string
}

type AccessGrantResource struct {
	Kind     string
	Name     string
	Selector *metav1.LabelSelector
}

func logicalPath(namespace, name string) string {
	return namespace + "/" + name
}

// ResolveLogicalID returns the kaos://<slug>/<ns>/<name> logical identity for a
// resource.
func ResolveLogicalID(slug, namespace, name string) string {
	return fmt.Sprintf("kaos://%s/%s", slug, logicalPath(namespace, name))
}

func edgeServiceClientID(kind EdgeKind, namespace, name string) string {
	segment := strings.ReplaceAll(logicalPath(namespace, name), "/", "-")
	return fmt.Sprintf("kaos-%s-%s", kind.Slug, segment)
}

func edgePermissionSetName(kind EdgeKind, namespace, name string) string {
	segment := strings.ReplaceAll(logicalPath(namespace, name), "/", ":")
	return fmt.Sprintf("kaos:%s:%s:%s", kind.Slug, segment, CallScope)
}

// AgentExternalID is the stable external identity for a KAOS agent in the
// projected authorization graph.
func AgentExternalID(namespace, name string) string {
	return ResolveLogicalID(AgentSlug, namespace, name)
}

// IsKAOSServiceClientID reports whether a broker service client_id was projected
// by KAOS (and is therefore safe to prune).
func IsKAOSServiceClientID(clientID string) bool {
	for _, p := range serviceClientIDPrefixes {
		if strings.HasPrefix(clientID, p) {
			return true
		}
	}
	return false
}

// IsKAOSPermissionSetName reports whether a permission-set name was projected by KAOS.
func IsKAOSPermissionSetName(name string) bool {
	return strings.HasPrefix(name, permissionSetPrefix)
}

// IsValidAgentExternalID reports whether external_id is a well-formed KAOS agent
// external id of the namespace-scoped form kaos://agent/<ns>/<name>.
func IsValidAgentExternalID(externalID string) bool {
	if !strings.HasPrefix(externalID, agentDisplayPrefix) {
		return false
	}
	rest := strings.TrimPrefix(externalID, agentDisplayPrefix)
	segments := strings.Split(rest, "/")
	if len(segments) != 2 {
		return false
	}
	for _, s := range segments {
		if s == "" {
			return false
		}
	}
	return true
}

// DesiredService is a synthetic service projected from an edge target.
type DesiredService struct {
	Namespace string
	Name      string
	Kind      EdgeKind
}

// ClientID is the synthetic client_id for the service.
func (s DesiredService) ClientID() string {
	return edgeServiceClientID(s.Kind, s.Namespace, s.Name)
}

// DesiredPermissionSet grants "call" on one synthetic service.
type DesiredPermissionSet struct {
	Namespace string
	Target    string
	Kind      EdgeKind
}

// Name is the permission-set name.
func (p DesiredPermissionSet) Name() string {
	return edgePermissionSetName(p.Kind, p.Namespace, p.Target)
}

// ServiceClientID is the client_id of the service this permission set grants on.
func (p DesiredPermissionSet) ServiceClientID() string {
	return edgeServiceClientID(p.Kind, p.Namespace, p.Target)
}

// ResourceID is the kaos://<slug>/<ns>/<name> logical identity of the resource
// this permission set grants access to. It is the value a Model-1 grant map
// associates with an actor and that the enforcement policy matches a request
// against.
func (p DesiredPermissionSet) ResourceID() string {
	return ResolveLogicalID(p.Kind.Slug, p.Namespace, p.Target)
}

// DesiredAgent is a projected agent derived from a KAOS Agent and its edges.
type DesiredAgent struct {
	Namespace          string
	Name               string
	PermissionSetNames []string
	Autonomous         bool
}

// ExternalID is the stable external identity for the agent in the projected
// authorization graph.
func (a DesiredAgent) ExternalID() string {
	return AgentExternalID(a.Namespace, a.Name)
}

// DesiredState is the full authorization graph projected from KAOS resources.
type DesiredState struct {
	Services       []DesiredService
	PermissionSets []DesiredPermissionSet
	Agents         []DesiredAgent
	Resources      []Resource
	AccessGrants   []AccessGrant
	// ThirdPartyServices is exchange-only input. It is ignored by the PDP data path.
	ThirdPartyServices []DesiredThirdPartyService
}

// DesiredThirdPartyService is the exchange-specific projection of a namespaced declaration.
type DesiredThirdPartyService struct {
	Namespace          string
	Name               string
	DisplayName        string
	ClientID           string
	ClientSecretName   string
	ClientSecretKey    string
	IssuerURI          string
	TokenEndpoint      string
	AuthorizeEndpoint  string
	Scopes             []ThirdPartyScope
	ProtectedResources []string
	RouteName          string
	Access             []ThirdPartyAccess
}

// ThirdPartyScope is an OAuth scope exposed by a declared service.
type ThirdPartyScope struct {
	Name        string
	Description string
}

// ThirdPartyAccess binds one Agent to a real subset of provider scopes.
type ThirdPartyAccess struct {
	Agent  string
	Scopes []string
}

// ThirdPartyPermissionSetName returns the stable per-Agent permission-set name.
func ThirdPartyPermissionSetName(namespace, service, agent string) string {
	return fmt.Sprintf("kaos:thirdparty:%s:%s:%s", namespace, service, agent)
}

// Project turns a list of KAOS resources into the desired authorization graph.
// MCP server, model API, memory store, and agent->agent access edges are all
// projected so an agent is authorized against every external dependency and peer
// it declares. Agents with no edges are skipped. Logical identity is always
// kaos://<slug>/<ns>/<name>, so identities are unique by construction and need
// no conflict resolution.
func Project(resources []Resource) DesiredState {
	state := DesiredState{Resources: resources}

	services := map[string]DesiredService{}
	permissionSets := map[string]DesiredPermissionSet{}

	ensureService := func(kind EdgeKind, ns, name string) {
		svc := DesiredService{Namespace: ns, Name: name, Kind: kind}
		if _, ok := services[svc.ClientID()]; !ok {
			services[svc.ClientID()] = svc
		}
	}
	ensurePermissionSet := func(kind EdgeKind, ns, name string) DesiredPermissionSet {
		ps := DesiredPermissionSet{Namespace: ns, Target: name, Kind: kind}
		if existing, ok := permissionSets[ps.Name()]; ok {
			return existing
		}
		permissionSets[ps.Name()] = ps
		return ps
	}

	// Pass 1: project every declared MCP/ModelAPI edge target as a synthetic
	// service. Agent peers are projected lazily in pass 2, only when an agent
	// declares an access edge to them.
	declaredKinds := map[string]EdgeKind{MCPServer.ResourceKind: MCPServer, ModelAPI.ResourceKind: ModelAPI}
	for _, r := range resources {
		kind, ok := declaredKinds[r.Kind]
		if !ok || r.Name == "" {
			continue
		}
		ensureService(kind, r.Namespace, r.Name)
	}

	// Pass 2: agents -- project edges and grants.
	for _, r := range resources {
		if r.Kind != AgentKind || r.Name == "" {
			continue
		}
		var psNames []string
		addEdge := func(kind EdgeKind, target string) {
			ensureService(kind, r.Namespace, target)
			ps := ensurePermissionSet(kind, r.Namespace, target)
			psNames = append(psNames, ps.Name())
		}
		for _, mcp := range r.MCPServers {
			addEdge(MCPServer, mcp)
		}
		if r.ModelAPI != "" {
			addEdge(ModelAPI, r.ModelAPI)
		}
		if r.MemoryStore != "" {
			addEdge(MemoryStore, r.MemoryStore)
		}
		for _, peer := range r.Access {
			if peer == "" || peer == r.Name {
				continue // skip empty and self edges
			}
			addEdge(Agent, peer)
		}
		if len(psNames) == 0 {
			continue
		}
		state.Agents = append(state.Agents, DesiredAgent{
			Namespace:          r.Namespace,
			Name:               r.Name,
			PermissionSetNames: psNames,
			Autonomous:         r.Autonomous,
		})
	}

	state.Services = make([]DesiredService, 0, len(services))
	for _, svc := range services {
		state.Services = append(state.Services, svc)
	}
	state.PermissionSets = make([]DesiredPermissionSet, 0, len(permissionSets))
	for _, ps := range permissionSets {
		state.PermissionSets = append(state.PermissionSets, ps)
	}
	return state
}
