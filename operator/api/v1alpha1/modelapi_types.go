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

// ConfigYamlSource defines the source of LiteLLM config YAML
type ConfigYamlSource struct {
	// FromString is the config YAML as a literal string
	// +kubebuilder:validation:Optional
	FromString string `json:"fromString,omitempty"`

	// FromSecretKeyRef is a reference to a Secret key containing the config YAML
	// +kubebuilder:validation:Optional
	FromSecretKeyRef *corev1.SecretKeySelector `json:"fromSecretKeyRef,omitempty"`
}

// +kubebuilder:object:generate=true

// ApiKeyValueFrom defines sources for API key values
type ApiKeyValueFrom struct {
	// SecretKeyRef is a reference to a secret key
	// +kubebuilder:validation:Optional
	SecretKeyRef *corev1.SecretKeySelector `json:"secretKeyRef,omitempty"`

	// ConfigMapKeyRef is a reference to a configmap key
	// +kubebuilder:validation:Optional
	ConfigMapKeyRef *corev1.ConfigMapKeySelector `json:"configMapKeyRef,omitempty"`
}

// +kubebuilder:object:generate=true

// ApiKeySource defines the source of an API key
type ApiKeySource struct {
	// Value is a direct string value (not recommended for production)
	// +kubebuilder:validation:Optional
	Value string `json:"value,omitempty"`

	// ValueFrom is a reference to a secret or configmap
	// +kubebuilder:validation:Optional
	ValueFrom *ApiKeyValueFrom `json:"valueFrom,omitempty"`
}

// +kubebuilder:object:generate=true

// ProxyConfig defines configuration for LiteLLM proxy mode
type ProxyConfig struct {
	// Models is the list of model identifiers supported by this proxy
	// Examples: ["openai/gpt-5-mini", "gemini/*", "*"]
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=1
	Models []string `json:"models"`

	// APIBase is the base URL of the backend LLM API to proxy to (e.g., http://host.docker.internal:11434)
	// Set as PROXY_API_BASE environment variable
	// +kubebuilder:validation:Optional
	APIBase string `json:"apiBase,omitempty"`

	// APIKey for authentication with the backend LLM API
	// Set as PROXY_API_KEY environment variable
	// +kubebuilder:validation:Optional
	APIKey *ApiKeySource `json:"apiKey,omitempty"`

	// ConfigYaml allows providing a custom LiteLLM config (for advanced multi-model routing)
	// When provided, used directly for LiteLLM config; models list is still used for Agent validation
	// +kubebuilder:validation:Optional
	ConfigYaml *ConfigYamlSource `json:"configYaml,omitempty"`

	// Env variables to pass to the proxy container
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// +kubebuilder:object:generate=true

// HostedConfig defines configuration for Ollama hosted mode
type HostedConfig struct {
	// Model is the Ollama model to run (e.g., smollm2:135m)
	Model string `json:"model"`

	// Env variables to pass to the Ollama server
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
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

	// HostedConfig contains configuration for Hosted mode (replaces serverConfig)
	// +kubebuilder:validation:Optional
	HostedConfig *HostedConfig `json:"hostedConfig,omitempty"`

	// GatewayRoute configures Gateway API routing (timeout, etc.)
	// +kubebuilder:validation:Optional
	GatewayRoute *GatewayRoute `json:"gatewayRoute,omitempty"`

	// PodSpec allows overriding the generated pod spec using strategic merge patch
	// +kubebuilder:validation:Optional
	PodSpec *corev1.PodSpec `json:"podSpec,omitempty"`
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

	// Deployment contains status information from the underlying Deployment
	// +kubebuilder:validation:Optional
	Deployment *DeploymentStatus `json:"deployment,omitempty"`
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
