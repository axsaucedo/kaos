package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// MemoryStorageType selects where long-term memory and the short-term window are persisted.
type MemoryStorageType string

const (
	// MemoryStorageLocal runs a single-container store with an embedded Chroma
	// PersistentClient and a SQLite short-term window on one PersistentVolume.
	MemoryStorageLocal MemoryStorageType = "local"
	// MemoryStorageExternal binds an external pgvector database via a connection secret.
	MemoryStorageExternal MemoryStorageType = "external"
)

// +kubebuilder:object:generate=true

// MemoryPersistentVolume describes the PersistentVolumeClaim provisioned in local mode.
type MemoryPersistentVolume struct {
	// Size is the requested storage size (e.g. "5Gi").
	// +kubebuilder:default="5Gi"
	Size string `json:"size,omitempty"`
}

// +kubebuilder:object:generate=true

// LocalMemoryStorage configures the single-container local storage mode.
type LocalMemoryStorage struct {
	// Provider is the local vector store implementation. Chroma is the only
	// supported provider because it pre-filters on scope for correct multi-tenant recall.
	// +kubebuilder:validation:Enum=chroma
	// +kubebuilder:default=chroma
	Provider string `json:"provider,omitempty"`

	// PersistentVolume sizes the PVC that backs Chroma and the SQLite short-term window.
	// +kubebuilder:validation:Optional
	PersistentVolume *MemoryPersistentVolume `json:"persistentVolume,omitempty"`
}

// +kubebuilder:object:generate=true

// ExternalMemoryStorage configures an external pgvector database.
type ExternalMemoryStorage struct {
	// Provider is the external vector store implementation.
	// +kubebuilder:validation:Enum=pgvector
	// +kubebuilder:default=pgvector
	Provider string `json:"provider,omitempty"`

	// ConnectionSecretRef references the Secret key holding the database DSN.
	// +kubebuilder:validation:Required
	ConnectionSecretRef *corev1.SecretKeySelector `json:"connectionSecretRef"`

	// EmbeddingDims is the embedding vector dimensionality for the pgvector column.
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:default=1536
	EmbeddingDims *int32 `json:"embeddingDims,omitempty"`
}

// +kubebuilder:object:generate=true

// MemoryStorage selects and configures the storage backend. The mode block for
// the selected type is optional in local mode (all fields default) but required
// in external mode, where the connection secret cannot be defaulted.
// +kubebuilder:validation:XValidation:rule="self.type != 'external' || has(self.external)",message="storage.external is required when storage.type is external"
type MemoryStorage struct {
	// Type selects the storage mode.
	// +kubebuilder:validation:Enum=local;external
	Type MemoryStorageType `json:"type"`

	// Local configures the single-container local mode. When omitted in local
	// mode the provider and persistent-volume size fall back to their defaults.
	// +kubebuilder:validation:Optional
	Local *LocalMemoryStorage `json:"local,omitempty"`

	// External configures the external pgvector mode.
	// +kubebuilder:validation:Optional
	External *ExternalMemoryStorage `json:"external,omitempty"`
}

// +kubebuilder:object:generate=true

// MemoryModelRef references a model served by an existing ModelAPI.
type MemoryModelRef struct {
	// ModelAPI is the name of a ModelAPI resource in the same namespace.
	// +kubebuilder:validation:Required
	ModelAPI string `json:"modelAPI"`

	// Model is the model identifier the ModelAPI serves.
	// +kubebuilder:validation:Required
	Model string `json:"model"`
}

// +kubebuilder:object:generate=true

// MemoryModels binds the two model roles the service needs.
type MemoryModels struct {
	// Summarization drives Mem0's long-term extraction prompt and the medium-term rolling digest.
	// +kubebuilder:validation:Required
	Summarization MemoryModelRef `json:"summarization"`

	// Embedding drives vector embedding for long-term recall.
	// +kubebuilder:validation:Required
	Embedding MemoryModelRef `json:"embedding"`
}

// +kubebuilder:object:generate=true

// MemoryExtractionConfig tunes the long-term extraction executor.
type MemoryExtractionConfig struct {
	// Concurrency is the size of the Mem0 extraction executor pool.
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:default=4
	Concurrency *int32 `json:"concurrency,omitempty"`

	// SystemPrompt overrides the system prompt for Mem0's long-term fact
	// extraction, steering which facts are distilled into long-term memory. When
	// empty the engine's built-in extraction prompt is used.
	// +kubebuilder:validation:Optional
	SystemPrompt string `json:"systemPrompt,omitempty"`
}

// +kubebuilder:object:generate=true

// MemorySummarizationConfig tunes the medium-term rolling digest summariser. It
// tunes the prompt only; the model itself is bound via models.summarization.
type MemorySummarizationConfig struct {
	// SystemPrompt overrides the system prompt used when folding overflowed
	// short-term turns into the rolling digest. When empty the service's built-in
	// summariser prompt is used.
	// +kubebuilder:validation:Optional
	SystemPrompt string `json:"systemPrompt,omitempty"`
}

// +kubebuilder:object:generate=true

// MemoryStoreSpec defines the desired state of MemoryStore. It carries only
// infrastructure, model bindings, and the two store-level operational knobs; the
// short-term-window, digest, and sweeper marks are memory-service defaults.
// +kubebuilder:validation:XValidation:rule="self.storage.type != 'local' || !has(self.replicas) || self.replicas == 1",message="replicas must be 1 in local storage mode"
type MemoryStoreSpec struct {
	// Engine is the long-term memory engine. Mem0 is the only supported engine today.
	// +kubebuilder:validation:Enum=mem0
	// +kubebuilder:default=mem0
	Engine string `json:"engine,omitempty"`

	// Storage selects and configures the storage backend.
	// +kubebuilder:validation:Required
	Storage MemoryStorage `json:"storage"`

	// Replicas overrides the number of memory-service replicas. When unset it
	// defaults by storage mode: external (stateless, shared Postgres) stores run
	// two replicas for availability, local (single-writer) stores run one.
	// +kubebuilder:validation:Minimum=1
	Replicas *int32 `json:"replicas,omitempty"`

	// Models binds the summarization and embedding model roles to existing ModelAPIs.
	// +kubebuilder:validation:Required
	Models MemoryModels `json:"models"`

	// Extraction tunes the long-term extraction executor.
	// +kubebuilder:validation:Optional
	Extraction *MemoryExtractionConfig `json:"extraction,omitempty"`

	// Summarization tunes the medium-term rolling-digest summariser prompt. The
	// summariser model itself is bound via models.summarization.
	// +kubebuilder:validation:Optional
	Summarization *MemorySummarizationConfig `json:"summarization,omitempty"`

	// DefaultFailureMode is the store-wide default for the write/forget path.
	// +kubebuilder:validation:Enum=soft;strict
	// +kubebuilder:default=soft
	DefaultFailureMode string `json:"defaultFailureMode,omitempty"`

	// GatewayRoute configures Gateway API routing (timeout, etc.) for the memory
	// service so agents reach it through the gateway data-plane rather than a
	// direct Service address.
	// +kubebuilder:validation:Optional
	GatewayRoute *GatewayRoute `json:"gatewayRoute,omitempty"`

	// Telemetry configures OpenTelemetry instrumentation for the memory service.
	// +kubebuilder:validation:Optional
	Telemetry *TelemetryConfig `json:"telemetry,omitempty"`

	// Container provides shorthand container overrides (image, env, resources)
	// for the memory-service container.
	// +kubebuilder:validation:Optional
	Container *ContainerOverride `json:"container,omitempty"`
}

// +kubebuilder:object:generate=true

// MemoryStoreStatus defines the observed state of MemoryStore.
type MemoryStoreStatus struct {
	// Phase of the deployment.
	// +kubebuilder:validation:Enum=Pending;Ready;Failed
	Phase string `json:"phase,omitempty"`

	// Ready indicates if the memory service is ready.
	Ready bool `json:"ready,omitempty"`

	// Endpoint is the in-cluster service endpoint for the memory service.
	Endpoint string `json:"endpoint,omitempty"`

	// Message provides additional status information.
	Message string `json:"message,omitempty"`

	// Deployment contains status information from the underlying Deployment.
	// +kubebuilder:validation:Optional
	Deployment *DeploymentStatus `json:"deployment,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=memstore;memstores
// +kubebuilder:printcolumn:name="Engine",type=string,JSONPath=`.spec.engine`
// +kubebuilder:printcolumn:name="Storage",type=string,JSONPath=`.spec.storage.type`
// +kubebuilder:printcolumn:name="Ready",type=boolean,JSONPath=`.status.ready`
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`

// MemoryStore is the Schema for the memorystores API.
type MemoryStore struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   MemoryStoreSpec   `json:"spec,omitempty"`
	Status MemoryStoreStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// MemoryStoreList contains a list of MemoryStore.
type MemoryStoreList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []MemoryStore `json:"items"`
}

func init() {
	SchemeBuilder.Register(&MemoryStore{}, &MemoryStoreList{})
}
