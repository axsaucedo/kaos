package aib

import (
	"fmt"

	"github.com/axsaucedo/kaos/operator/internal/projection"
)

// ServiceBody is the identity-broker admin create payload for a synthetic
// service projected from an edge target. It is the Model-2 (broker
// permission-set) serialization of the pure projection graph; the graph itself
// carries no broker-specific shape.
func ServiceBody(s projection.DesiredService) map[string]any {
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
		"scopes": []any{map[string]any{"scope_value": projection.CallScope, "description": s.Kind.ScopeDescription}},
	}
}

// PermissionSetBody is the identity-broker admin create payload for a permission
// set granting "call" on one synthetic service.
func PermissionSetBody(p projection.DesiredPermissionSet, serviceID string) map[string]any {
	return map[string]any{
		"name":        p.Name(),
		"description": fmt.Sprintf("call %s/%s", p.Namespace, p.Target),
		"service_scopes": []any{map[string]any{
			"service_id":       serviceID,
			"scopes":           []any{projection.CallScope},
			"requirement_type": "mandatory",
		}},
	}
}

// AgentBody is the identity-broker admin create payload binding an agent to its
// permission sets.
func AgentBody(a projection.DesiredAgent, permissionSetIDs []string) map[string]any {
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

// logicalPath mirrors the projection package's namespace/name path used in
// broker display and issuer fields.
func logicalPath(namespace, name string) string {
	return namespace + "/" + name
}
