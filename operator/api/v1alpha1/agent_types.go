package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// +kubebuilder:object:generate=true

// AgentNetworkConfig defines A2A communication settings
type AgentNetworkConfig struct {
	// Expose indicates if this agent exposes an Agent Card endpoint for A2A
	// +kubebuilder:default=true
	Expose *bool `json:"expose,omitempty"`

	// Access is the allowlist of peer agent names this agent can call
	// +kubebuilder:validation:Optional
	Access []string `json:"access,omitempty"`
}

// +kubebuilder:object:generate=true

// +kubebuilder:object:generate=true

// MemoryConfig defines memory settings for the agent
type MemoryConfig struct {
	// Enabled controls whether memory is enabled (default: true)
	// When disabled, NullMemory is used (no-op implementation)
	// +kubebuilder:default=true
	Enabled *bool `json:"enabled,omitempty"`

	// Type specifies the memory implementation (default: "local")
	// Currently only "local" is supported
	// +kubebuilder:default="local"
	// +kubebuilder:validation:Enum=local
	Type string `json:"type,omitempty"`

	// ContextLimit is the number of messages to include in delegation context (default: 6)
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=100
	// +kubebuilder:default=6
	ContextLimit *int32 `json:"contextLimit,omitempty"`

	// MaxSessions is the maximum number of sessions to keep in memory (default: 1000)
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=100000
	// +kubebuilder:default=1000
	MaxSessions *int32 `json:"maxSessions,omitempty"`

	// MaxSessionEvents is the maximum events per session before eviction (default: 500)
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=10000
	// +kubebuilder:default=500
	MaxSessionEvents *int32 `json:"maxSessionEvents,omitempty"`
}

// +kubebuilder:object:generate=true

// TelemetryConfig defines OpenTelemetry instrumentation settings.
// Advanced OTel settings can be configured via spec.config.env using standard
// OTEL_* environment variables (e.g., OTEL_EXPORTER_OTLP_INSECURE, OTEL_TRACES_SAMPLER).
type TelemetryConfig struct {
	// Enabled controls whether OpenTelemetry is enabled (default: false)
	// When enabled, traces, metrics, and log correlation are all active.
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// Endpoint is the OTLP gRPC endpoint URL (required when enabled).
	// Example: "http://otel-collector.observability:4317"
	// +kubebuilder:validation:Optional
	Endpoint string `json:"endpoint,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentConfig defines agent-specific configuration
type AgentConfig struct {
	// Description is a human-readable description of the agent
	// +kubebuilder:validation:Optional
	Description string `json:"description,omitempty"`

	// Instructions are the system instructions for the agent
	// +kubebuilder:validation:Optional
	Instructions string `json:"instructions,omitempty"`

	// ReasoningLoopMaxSteps is the maximum number of reasoning steps before stopping
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=20
	// +kubebuilder:default=5
	ReasoningLoopMaxSteps *int32 `json:"reasoningLoopMaxSteps,omitempty"`

	// Memory configures the agent's memory system
	// +kubebuilder:validation:Optional
	Memory *MemoryConfig `json:"memory,omitempty"`

	// Telemetry configures OpenTelemetry instrumentation
	// +kubebuilder:validation:Optional
	Telemetry *TelemetryConfig `json:"telemetry,omitempty"`

	// Env variables to pass to the agent runtime
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentSpec defines the desired state of Agent
type AgentSpec struct {
	// ModelAPI is the name of the ModelAPI resource this agent uses
	ModelAPI string `json:"modelAPI"`

	// Model is the model identifier this agent uses (e.g., "openai/gpt-4", "ollama/smollm2:135m")
	// Must be supported by the referenced ModelAPI
	Model string `json:"model"`

	// MCPServers is a list of MCPServer names this agent can use
	// +kubebuilder:validation:Optional
	MCPServers []string `json:"mcpServers,omitempty"`

	// AgentNetwork defines A2A communication settings
	// +kubebuilder:validation:Optional
	AgentNetwork *AgentNetworkConfig `json:"agentNetwork,omitempty"`

	// Config contains agent-specific configuration
	// +kubebuilder:validation:Optional
	Config *AgentConfig `json:"config,omitempty"`

	// WaitForDependencies controls whether the agent waits for ModelAPI and MCPServers to be ready
	// before creating the deployment. Default is true.
	// +kubebuilder:default=true
	WaitForDependencies *bool `json:"waitForDependencies,omitempty"`

	// GatewayRoute configures Gateway API routing (timeout, etc.)
	// +kubebuilder:validation:Optional
	GatewayRoute *GatewayRoute `json:"gatewayRoute,omitempty"`

	// PodSpec allows overriding the generated pod spec using strategic merge patch
	// +kubebuilder:validation:Optional
	PodSpec *corev1.PodSpec `json:"podSpec,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentStatus defines the observed state of Agent
type AgentStatus struct {
	// Phase of the deployment
	// +kubebuilder:validation:Enum=Pending;Ready;Failed;Waiting
	Phase string `json:"phase,omitempty"`

	// Ready indicates if the agent is ready
	Ready bool `json:"ready,omitempty"`

	// Endpoint is the Agent Card HTTP endpoint for A2A communication
	// +kubebuilder:validation:Optional
	Endpoint string `json:"endpoint,omitempty"`

	// LinkedResources tracks references to ModelAPI and MCPServer resources
	// +kubebuilder:validation:Optional
	LinkedResources map[string]string `json:"linkedResources,omitempty"`

	// Message provides additional status information
	Message string `json:"message,omitempty"`

	// Deployment contains status information from the underlying Deployment
	// +kubebuilder:validation:Optional
	Deployment *DeploymentStatus `json:"deployment,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=agent;agents
// +kubebuilder:printcolumn:name="ModelAPI",type=string,JSONPath=`.spec.modelAPI`
// +kubebuilder:printcolumn:name="Model",type=string,JSONPath=`.spec.model`
// +kubebuilder:printcolumn:name="Ready",type=boolean,JSONPath=`.status.ready`
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`

// Agent is the Schema for the agents API
type Agent struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   AgentSpec   `json:"spec,omitempty"`
	Status AgentStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// AgentList contains a list of Agent
type AgentList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Agent `json:"items"`
}

func init() {
	SchemeBuilder.Register(&Agent{}, &AgentList{})
}
