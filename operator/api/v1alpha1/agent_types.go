package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// +kubebuilder:object:generate=true

// AgentNetworkConfig defines A2A communication settings
type AgentNetworkConfig struct {
	// Expose indicates if this agent exposes an Agent Card endpoint for A2A
	// +kubebuilder:validation:Optional
	Expose bool `json:"expose,omitempty"`

	// Access is the allowlist of peer agent names this agent can call
	// +kubebuilder:validation:Optional
	Access []string `json:"access,omitempty"`
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

	// Env variables to pass to the agent runtime
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentSpec defines the desired state of Agent
type AgentSpec struct {
	// ModelAPI is the name of the ModelAPI resource this agent uses
	ModelAPI string `json:"modelAPI"`

	// MCPServers is a list of MCPServer names this agent can use
	// +kubebuilder:validation:Optional
	MCPServers []string `json:"mcpServers,omitempty"`

	// AgentNetwork defines A2A communication settings
	// +kubebuilder:validation:Optional
	AgentNetwork *AgentNetworkConfig `json:"agentNetwork,omitempty"`

	// Config contains agent-specific configuration
	// +kubebuilder:validation:Optional
	Config *AgentConfig `json:"config,omitempty"`

	// Resources defines compute resources for the agent
	// +kubebuilder:validation:Optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`

	// Replicas is the desired number of agent replicas
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Optional
	Replicas *int32 `json:"replicas,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentStatus defines the observed state of Agent
type AgentStatus struct {
	// Phase of the deployment
	// +kubebuilder:validation:Enum=Pending;Ready;Failed
	Phase string `json:"phase,omitempty"`

	// Ready indicates if the agent is ready
	Ready bool `json:"ready,omitempty"`

	// ObservedReplicas is the number of observed agent replicas
	ObservedReplicas int32 `json:"observedReplicas,omitempty"`

	// Endpoint is the Agent Card HTTP endpoint for A2A communication
	// +kubebuilder:validation:Optional
	Endpoint string `json:"endpoint,omitempty"`

	// LinkedResources tracks references to ModelAPI and MCPServer resources
	// +kubebuilder:validation:Optional
	LinkedResources map[string]string `json:"linkedResources,omitempty"`

	// Message provides additional status information
	Message string `json:"message,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:subresource:scale:specpath=.spec.replicas,statuspath=.status.observedReplicas
// +kubebuilder:resource:shortName=agent;agents
// +kubebuilder:printcolumn:name="ModelAPI",type=string,JSONPath=`.spec.modelAPI`
// +kubebuilder:printcolumn:name="Replicas",type=integer,JSONPath=`.status.observedReplicas`
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
