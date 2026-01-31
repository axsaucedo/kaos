package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// +kubebuilder:object:generate=true

// MCPServerSpec defines the desired state of MCPServer
type MCPServerSpec struct {
	// Runtime identifier from ConfigMap registry or "custom"
	// Examples: "python-string", "kubernetes", "slack", "custom"
	// +kubebuilder:validation:Required
	Runtime string `json:"runtime"`

	// Params is runtime-specific configuration (string, typically YAML)
	// Passed to container via runtime's paramsEnvVar (e.g., MCP_TOOLS_STRING for python-string)
	// +kubebuilder:validation:Optional
	Params string `json:"params,omitempty"`

	// ServiceAccountName for RBAC (e.g., for kubernetes runtime)
	// Created via `kaos system create-rbac`
	// +kubebuilder:validation:Optional
	ServiceAccountName string `json:"serviceAccountName,omitempty"`

	// Telemetry configures OpenTelemetry instrumentation
	// +kubebuilder:validation:Optional
	Telemetry *TelemetryConfig `json:"telemetry,omitempty"`

	// GatewayRoute configures Gateway API routing (timeout, etc.)
	// +kubebuilder:validation:Optional
	GatewayRoute *GatewayRoute `json:"gatewayRoute,omitempty"`

	// Container provides shorthand container overrides (image, env, resources)
	// For "custom" runtime, container.image is required
	// +kubebuilder:validation:Optional
	Container *ContainerOverride `json:"container,omitempty"`

	// PodSpec allows overriding the generated pod spec using strategic merge patch
	// +kubebuilder:validation:Optional
	PodSpec *corev1.PodSpec `json:"podSpec,omitempty"`
}

// +kubebuilder:object:generate=true

// MCPServerStatus defines the observed state of MCPServer
type MCPServerStatus struct {
	// Phase of the deployment
	// +kubebuilder:validation:Enum=Pending;Ready;Failed
	Phase string `json:"phase,omitempty"`

	// Ready indicates if the MCP server is ready
	Ready bool `json:"ready,omitempty"`

	// Endpoint is the service endpoint for the MCP server
	Endpoint string `json:"endpoint,omitempty"`

	// AvailableTools lists tools exposed by this server
	// +kubebuilder:validation:Optional
	AvailableTools []string `json:"availableTools,omitempty"`

	// Message provides additional status information
	Message string `json:"message,omitempty"`

	// Deployment contains status information from the underlying Deployment
	// +kubebuilder:validation:Optional
	Deployment *DeploymentStatus `json:"deployment,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=mcp;mcps
// +kubebuilder:printcolumn:name="Runtime",type=string,JSONPath=`.spec.runtime`
// +kubebuilder:printcolumn:name="Ready",type=boolean,JSONPath=`.status.ready`
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`

// MCPServer is the Schema for the mcpservers API
type MCPServer struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   MCPServerSpec   `json:"spec,omitempty"`
	Status MCPServerStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// MCPServerList contains a list of MCPServer
type MCPServerList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []MCPServer `json:"items"`
}

func init() {
	SchemeBuilder.Register(&MCPServer{}, &MCPServerList{})
}
