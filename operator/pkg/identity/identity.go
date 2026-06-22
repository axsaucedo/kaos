// Package identity resolves the logical security identity of KAOS resources.
//
// Every Agent, MCPServer and ModelAPI has a logical identity of the form
// kaos://{kind}/{path}. By default the path is namespace-scoped
// ({namespace}/{name}) so identities are unique without any user input. When a
// resource sets spec.security.id, the path becomes that single id
// ({kind}/{id}), giving the resource a stable, namespace-independent identity
// that survives a namespace move or rename. The same rule is mirrored in the
// sync service projection so the operator and sync service always agree on the
// identity a resource is provisioned under.
package identity

import "fmt"

// Kind is the resource kind segment used in a logical identity URI.
type Kind string

const (
	// KindAgent is the identity kind for Agent resources.
	KindAgent Kind = "agent"
	// KindMCPServer is the identity kind for MCPServer resources.
	KindMCPServer Kind = "mcpserver"
	// KindModelAPI is the identity kind for ModelAPI resources.
	KindModelAPI Kind = "modelapi"
)

// Resolve returns the logical identity URI for a resource. When securityID is
// non-empty the identity is namespace-independent (kaos://{kind}/{id});
// otherwise it falls back to the namespace-scoped default
// (kaos://{kind}/{namespace}/{name}).
func Resolve(kind Kind, namespace, name, securityID string) string {
	if securityID != "" {
		return fmt.Sprintf("kaos://%s/%s", kind, securityID)
	}
	return fmt.Sprintf("kaos://%s/%s/%s", kind, namespace, name)
}
