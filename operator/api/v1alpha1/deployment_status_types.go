package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// +kubebuilder:object:generate=true

// DeploymentStatus mirrors key status fields from the underlying Deployment.
// This provides visibility into rolling update progress and pod availability.
type DeploymentStatus struct {
	// Replicas is the total number of non-terminated pods targeted by this deployment.
	// +kubebuilder:validation:Optional
	Replicas int32 `json:"replicas,omitempty"`

	// ReadyReplicas is the number of pods with a Ready condition.
	// +kubebuilder:validation:Optional
	ReadyReplicas int32 `json:"readyReplicas,omitempty"`

	// AvailableReplicas is the number of pods that are available (ready for minReadySeconds).
	// +kubebuilder:validation:Optional
	AvailableReplicas int32 `json:"availableReplicas,omitempty"`

	// UpdatedReplicas is the number of pods with the desired pod template spec.
	// During a rolling update, this shows progress toward the new version.
	// +kubebuilder:validation:Optional
	UpdatedReplicas int32 `json:"updatedReplicas,omitempty"`

	// Conditions represent the latest available observations of the deployment's state.
	// Typical conditions include Available, Progressing, and ReplicaFailure.
	// +kubebuilder:validation:Optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}
