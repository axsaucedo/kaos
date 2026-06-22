package v1alpha1

// SecuritySpec holds the per-resource security configuration. The logical
// security identity override is the only per-resource security field: there are
// deliberately no per-resource authentication or authorization overrides.
type SecuritySpec struct {
	// ID overrides the logical security identity of the resource. When set, the
	// resolved identity becomes kaos://{kind}/{id} (namespace-independent),
	// letting the resource keep a stable identity across a namespace move or a
	// rename so delegated grants survive. When omitted, the identity defaults to
	// kaos://{kind}/{namespace}/{name}. An explicit id is a shared logical
	// identity and must be unique per kind among active resources. The value is
	// embedded directly after kaos://{kind}/, so it is restricted to a safe path
	// segment (lowercase alphanumerics, '-', '_', '.').
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Pattern=`^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$`
	ID string `json:"id,omitempty"`
}

// GetID returns the configured security identity override, or the empty string
// when no SecuritySpec or id is set. Safe to call on a nil receiver.
func (s *SecuritySpec) GetID() string {
	if s == nil {
		return ""
	}
	return s.ID
}
