// Package projection turns KAOS resources into the desired Agentic Identity
// Broker (AIB) state. It is pure (no I/O) so it can be unit tested without a
// cluster or a broker.
//
// Each edge target <ns>/<name> of kind <slug> becomes a synthetic AIB service
// whose client_id is kaos-<slug>-<ns>-<name> exposing a single "call" scope.
// Each requested edge Agent -> target becomes a permission set granting that
// scope, and each Agent becomes a local AIB agent bound to the permission sets
// for its requested edges. The resource an agent is authorized against is
// kaos://<slug>/<ns>/<name>, which is unique by construction.
package projection

import (
	"fmt"
	"strings"
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

// EdgeKind is an edge target kind and the vocabulary used to encode it into AIB.
type EdgeKind struct {
	Slug             string // identifier segment, e.g. "mcpserver" / "modelapi"
	ResourceKind     string // KAOS resource kind, e.g. "MCPServer" / "ModelAPI"
	DisplayLabel     string // human label used in display names
	ScopeDescription string // description attached to the synthetic "call" scope
}

// The two edge kinds an agent can request.
var (
	MCPServer = EdgeKind{Slug: "mcpserver", ResourceKind: "MCPServer", DisplayLabel: "MCPServer", ScopeDescription: "Invoke the MCP server"}
	ModelAPI  = EdgeKind{Slug: "modelapi", ResourceKind: "ModelAPI", DisplayLabel: "ModelAPI", ScopeDescription: "Invoke the model API"}
)

var serviceClientIDPrefixes = []string{"kaos-" + MCPServer.Slug + "-", "kaos-" + ModelAPI.Slug + "-"}

// Resource is the minimal KAOS resource shape the projection needs. The runtime
// converts unstructured CRDs into this; tests construct it directly.
type Resource struct {
	Kind       string
	Namespace  string
	Name       string
	MCPServers []string // spec.mcpServers (Agent only)
	ModelAPI   string   // spec.modelAPI (Agent only)
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

// AgentExternalID is the stable external identity for a KAOS agent in AIB.
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

// DesiredService is a synthetic AIB service projected from an edge target.
type DesiredService struct {
	Namespace string
	Name      string
	Kind      EdgeKind
}

// ClientID is the synthetic broker client_id for the service.
func (s DesiredService) ClientID() string {
	return edgeServiceClientID(s.Kind, s.Namespace, s.Name)
}

// AdminBody is the AIB admin create payload for the service.
func (s DesiredService) AdminBody() map[string]any {
	path := logicalPath(s.Namespace, s.Name)
	return map[string]any{
		"display_name":  fmt.Sprintf("KAOS %s %s (synthetic)", s.Kind.DisplayLabel, path),
		"client_id":     s.ClientID(),
		"client_secret": "synthetic",
		"issuer_uri":    fmt.Sprintf("https://kaos.local/%s/%s", s.Kind.Slug, path),
		"discovery":     map[string]any{"enable_discovery": false},
		"endpoints": map[string]any{
			"token_endpoint":     "https://kaos.local/t",
			"authorize_endpoint": "https://kaos.local/a",
		},
		"scopes": []any{map[string]any{"scope_value": CallScope, "description": s.Kind.ScopeDescription}},
	}
}

// DesiredPermissionSet grants "call" on one synthetic service.
type DesiredPermissionSet struct {
	Namespace string
	Target    string
	Kind      EdgeKind
}

// Name is the broker permission-set name.
func (p DesiredPermissionSet) Name() string {
	return edgePermissionSetName(p.Kind, p.Namespace, p.Target)
}

// ServiceClientID is the client_id of the service this permission set grants on.
func (p DesiredPermissionSet) ServiceClientID() string {
	return edgeServiceClientID(p.Kind, p.Namespace, p.Target)
}

// AdminBody is the AIB admin create payload for the permission set.
func (p DesiredPermissionSet) AdminBody(serviceID string) map[string]any {
	return map[string]any{
		"name":        p.Name(),
		"description": fmt.Sprintf("call %s/%s", p.Namespace, p.Target),
		"service_scopes": []any{map[string]any{
			"service_id":       serviceID,
			"scopes":           []any{CallScope},
			"requirement_type": "mandatory",
		}},
	}
}

// DesiredAgent is a local AIB agent projected from a KAOS Agent and its edges.
type DesiredAgent struct {
	Namespace          string
	Name               string
	PermissionSetNames []string
}

// ExternalID is the stable external identity for the agent in AIB.
func (a DesiredAgent) ExternalID() string {
	return AgentExternalID(a.Namespace, a.Name)
}

// AdminBody is the AIB admin create payload binding the agent to permission sets.
func (a DesiredAgent) AdminBody(permissionSetIDs []string) map[string]any {
	bindings := make([]any, 0, len(permissionSetIDs))
	for _, pid := range permissionSetIDs {
		bindings = append(bindings, map[string]any{"permission_set_id": pid, "requirement_type": "mandatory"})
	}
	return map[string]any{
		"display_name":    a.ExternalID(),
		"description":     fmt.Sprintf("KAOS agent %s/%s", a.Namespace, a.Name),
		"permission_sets": bindings,
	}
}

// DesiredState is the full desired AIB state projected from KAOS resources.
type DesiredState struct {
	Services       []DesiredService
	PermissionSets []DesiredPermissionSet
	Agents         []DesiredAgent
}

// Project turns a list of KAOS resources into the desired AIB state. Both MCP
// server edges and the model API edge are projected so an agent is authorized
// against every external dependency it declares. Agents with no edges are
// skipped. Logical identity is always kaos://<slug>/<ns>/<name>, so identities
// are unique by construction and need no conflict resolution.
func Project(resources []Resource) DesiredState {
	var state DesiredState

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

	// Pass 1: project every declared edge target as a synthetic service.
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
		if len(psNames) == 0 {
			continue
		}
		state.Agents = append(state.Agents, DesiredAgent{
			Namespace:          r.Namespace,
			Name:               r.Name,
			PermissionSetNames: psNames,
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
