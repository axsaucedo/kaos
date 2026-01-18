package util

import (
	appsv1 "k8s.io/api/apps/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// CopyDeploymentStatus creates a DeploymentStatus from a Kubernetes Deployment's status.
// This mirrors key status fields to provide visibility into rolling updates.
func CopyDeploymentStatus(deployment *appsv1.Deployment) *kaosv1alpha1.DeploymentStatus {
	if deployment == nil {
		return nil
	}

	status := &kaosv1alpha1.DeploymentStatus{
		Replicas:          deployment.Status.Replicas,
		ReadyReplicas:     deployment.Status.ReadyReplicas,
		AvailableReplicas: deployment.Status.AvailableReplicas,
		UpdatedReplicas:   deployment.Status.UpdatedReplicas,
	}

	// Convert deployment conditions to metav1.Condition format
	for _, cond := range deployment.Status.Conditions {
		status.Conditions = append(status.Conditions, metav1.Condition{
			Type:               string(cond.Type),
			Status:             metav1.ConditionStatus(cond.Status),
			LastTransitionTime: cond.LastTransitionTime,
			Reason:             cond.Reason,
			Message:            cond.Message,
		})
	}

	return status
}
