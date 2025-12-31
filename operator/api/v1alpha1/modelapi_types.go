package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ModelAPIMode defines the mode for model API deployment
type ModelAPIMode string

const (
	// ModelAPIModeProxy means using LiteLLM to proxy to external model
	ModelAPIModeProxy ModelAPIMode = "Proxy"
	// ModelAPIModeHosted means hosting model using vLLM in-cluster
	ModelAPIModeHosted ModelAPIMode = "Hosted"
)

// +kubebuilder:object:generate=true

// ProxyConfig defines configuration for LiteLLM proxy mode
type ProxyConfig struct {
	// APIBase is the base URL of the backend LLM API to proxy to (e.g., http://host.docker.internal:11434)
	// +kubebuilder:validation:Optional
	APIBase string `json:"apiBase,omitempty"`

	// Model is the model identifier to proxy (e.g., ollama/smollm2:135m)
	// +kubebuilder:validation:Optional
	Model string `json:"model,omitempty"`

	// ConfigYaml allows providing a custom LiteLLM config (for advanced multi-model routing)
	// If provided, APIBase and Model are ignored and this config is used instead
	// +kubebuilder:validation:Optional
	ConfigYaml string `json:"configYaml,omitempty"`

	// Env variables to pass to the proxy container
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// +kubebuilder:object:generate=true

// ServerConfig defines configuration for vLLM hosted mode
type ServerConfig struct {
	// Model is the HuggingFace model ID or path
	Model string `json:"model"`

	// Env variables to pass to the vLLM server
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`

	// Resources defines compute resources for the server
	// +kubebuilder:validation:Optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`
}

// +kubebuilder:object:generate=true

// ModelAPISpec defines the desired state of ModelAPI
type ModelAPISpec struct {
	// Mode specifies the deployment mode (Proxy or Hosted)
	// +kubebuilder:validation:Enum=Proxy;Hosted
	Mode ModelAPIMode `json:"mode"`

	// ProxyConfig contains configuration for Proxy mode
	// +kubebuilder:validation:Optional
	ProxyConfig *ProxyConfig `json:"proxyConfig,omitempty"`

	// ServerConfig contains configuration for Hosted mode
	// +kubebuilder:validation:Optional
	ServerConfig *ServerConfig `json:"serverConfig,omitempty"`
}

// +kubebuilder:object:generate=true

// ModelAPIStatus defines the observed state of ModelAPI
type ModelAPIStatus struct {
	// Phase of the deployment
	// +kubebuilder:validation:Enum=Pending;Ready;Failed
	Phase string `json:"phase,omitempty"`

	// Ready indicates if the model API is ready
	Ready bool `json:"ready,omitempty"`

	// Endpoint is the service endpoint for the model API
	Endpoint string `json:"endpoint,omitempty"`

	// Message provides additional status information
	Message string `json:"message,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=api;apis
// +kubebuilder:printcolumn:name="Mode",type=string,JSONPath=`.spec.mode`
// +kubebuilder:printcolumn:name="Ready",type=boolean,JSONPath=`.status.ready`
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`

// ModelAPI is the Schema for the modelapis API
type ModelAPI struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ModelAPISpec   `json:"spec,omitempty"`
	Status ModelAPIStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// ModelAPIList contains a list of ModelAPI
type ModelAPIList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ModelAPI `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ModelAPI{}, &ModelAPIList{})
}
