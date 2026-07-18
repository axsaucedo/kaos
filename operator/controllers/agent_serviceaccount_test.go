package controllers

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestReconcileAgentServiceAccountCreatesOwnedIdentity(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_IDENTITY_PROVIDER", "serviceaccount")
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher", UID: "agent-uid"}}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	r := &AgentReconciler{Client: c, Scheme: scheme}
	if err := r.reconcileAgentServiceAccount(context.Background(), agent); err != nil {
		t.Fatalf("reconcileAgentServiceAccount: %v", err)
	}
	sa := &corev1.ServiceAccount{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "demo", Name: "kaos-agent-researcher"}, sa); err != nil {
		t.Fatalf("get ServiceAccount: %v", err)
	}
	if len(sa.OwnerReferences) != 1 || sa.OwnerReferences[0].UID != agent.UID || sa.OwnerReferences[0].Controller == nil || !*sa.OwnerReferences[0].Controller {
		t.Fatalf("unexpected owner references: %#v", sa.OwnerReferences)
	}
}

func TestConstructAgentDeploymentUsesProjectedServiceAccountIdentity(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_IDENTITY_PROVIDER", "serviceaccount")
	t.Setenv("DEFAULT_AGENT_IMAGE", "example/agent:test")
	agent := newAgent("demo", "researcher")
	deployment, err := (&AgentReconciler{}).constructDeployment(agent, &kaosv1alpha1.ModelAPI{}, map[string]string{}, map[string]string{}, "", "", "")
	if err != nil {
		t.Fatalf("constructDeployment: %v", err)
	}
	pod := deployment.Spec.Template.Spec
	if pod.ServiceAccountName != "kaos-agent-researcher" {
		t.Fatalf("serviceAccountName = %q", pod.ServiceAccountName)
	}
	if pod.AutomountServiceAccountToken == nil || *pod.AutomountServiceAccountToken {
		t.Fatal("default ServiceAccount token automount must be disabled")
	}
}
