package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// MCPServerType defines the type of MCP server runtime
type MCPServerType string

const (
	// MCPServerTypePython means using Python-based MCP server
	MCPServerTypePython MCPServerType = "python-runtime"
	// MCPServerTypeNode means using Node.js-based MCP server (future)
	MCPServerTypeNode MCPServerType = "node-runtime"
)

// +kubebuilder:object:generate=true

// MCPToolsConfig defines the tools configuration for MCP server
type MCPToolsConfig struct {
	// FromPackage is the package name to run with uvx (e.g., "mcp-server-calculator")
	// For python-runtime type: runs as "uvx <package-name>"
	// The package must be available on PyPI
	// +kubebuilder:validation:Optional
	FromPackage string `json:"fromPackage,omitempty"`

	// FromString is a Python literal string defining tools dynamically
	// When set, the MCP server uses MCP_TOOLS_STRING env var instead of uvx package
	// +kubebuilder:validation:Optional
	FromString string `json:"fromString,omitempty"`

	// FromSecretKeyRef is a reference to a Secret key containing tool definitions
	// +kubebuilder:validation:Optional
	FromSecretKeyRef *corev1.SecretKeySelector `json:"fromSecretKeyRef,omitempty"`
}

// +kubebuilder:object:generate=true

// MCPServerConfig defines the configuration for MCP server
type MCPServerConfig struct {
	// Tools configures how MCP tools are loaded
	// +kubebuilder:validation:Optional
	Tools *MCPToolsConfig `json:"tools,omitempty"`

	// Telemetry configures OpenTelemetry instrumentation
	// +kubebuilder:validation:Optional
	Telemetry *TelemetryConfig `json:"telemetry,omitempty"`

	// Env variables to pass to the MCP server
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// +kubebuilder:object:generate=true

// MCPServerSpec defines the desired state of MCPServer
type MCPServerSpec struct {
	// Type specifies the MCP server runtime type
	// +kubebuilder:validation:Enum=python-runtime;node-runtime
	Type MCPServerType `json:"type"`

	// Config contains the MCP server configuration
	Config MCPServerConfig `json:"config"`

	// GatewayRoute configures Gateway API routing (timeout, etc.)
	// +kubebuilder:validation:Optional
	GatewayRoute *GatewayRoute `json:"gatewayRoute,omitempty"`

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
// +kubebuilder:printcolumn:name="Type",type=string,JSONPath=`.spec.type`
// +kubebuilder:printcolumn:name="MCP",type=string,JSONPath=`.spec.config.mcp`
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
