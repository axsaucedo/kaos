package v1alpha1

// +kubebuilder:object:generate=true

// GatewayRoute defines Gateway API routing configuration for a resource.
// This is a shared type used by Agent, ModelAPI, and MCPServer.
type GatewayRoute struct {
	// Timeout specifies the request timeout for the HTTPRoute.
	// This is a Gateway API Duration string (e.g., "30s", "1m", "5m").
	// If not specified, defaults to "60s" for ModelAPI (to accommodate LLM inference)
	// and "30s" for Agent and MCPServer.
	// Set to "0s" to disable timeout (use Gateway's default).
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Pattern=`^([0-9]+(h|m|s|ms)){1,4}$`
	Timeout string `json:"timeout,omitempty"`
}
