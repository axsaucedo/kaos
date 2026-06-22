package controllers

import (
	"context"
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func conflictScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := kaosv1alpha1.AddToScheme(s); err != nil {
		t.Fatalf("add to scheme: %v", err)
	}
	return s
}

func agentWithIDAndAge(namespace, name, id string, created time.Time) *kaosv1alpha1.Agent {
	a := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{
			Namespace:         namespace,
			Name:              name,
			CreationTimestamp: metav1.NewTime(created),
			Finalizers:        []string{agentFinalizerName},
		},
		Spec: kaosv1alpha1.AgentSpec{
			ModelAPI: "m",
			Model:    "x",
			Security: &kaosv1alpha1.SecuritySpec{ID: id},
		},
	}
	a.Status.Phase = "Pending"
	return a
}

func reconcileAgent(t *testing.T, r *AgentReconciler, a *kaosv1alpha1.Agent) {
	t.Helper()
	if _, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: types.NamespacedName{Namespace: a.Namespace, Name: a.Name},
	}); err != nil {
		t.Fatalf("reconcile %s/%s: %v", a.Namespace, a.Name, err)
	}
}

func getAgent(t *testing.T, r *AgentReconciler, namespace, name string) *kaosv1alpha1.Agent {
	t.Helper()
	got := &kaosv1alpha1.Agent{}
	if err := r.Get(context.Background(), types.NamespacedName{Namespace: namespace, Name: name}, got); err != nil {
		t.Fatalf("get %s/%s: %v", namespace, name, err)
	}
	return got
}

// TestAgentIdentityConflictNewerIsRejected verifies that when two Agents share
// an explicit security.id, the newer one is marked Failed while the older keeps
// its identity, and that deleting the older lets the newer adopt the id.
func TestAgentIdentityConflictNewerIsRejected(t *testing.T) {
	older := agentWithIDAndAge("ns-a", "older", "shared", time.Unix(100, 0))
	newer := agentWithIDAndAge("ns-b", "newer", "shared", time.Unix(200, 0))

	cl := fake.NewClientBuilder().
		WithScheme(conflictScheme(t)).
		WithObjects(older, newer).
		WithStatusSubresource(older, newer).
		Build()
	r := &AgentReconciler{Client: cl, Scheme: conflictScheme(t)}

	reconcileAgent(t, r, newer)
	gotNewer := getAgent(t, r, "ns-b", "newer")
	if gotNewer.Status.Phase != "Failed" {
		t.Errorf("newer Agent Phase = %q, want Failed", gotNewer.Status.Phase)
	}
	if gotNewer.Status.Ready {
		t.Errorf("newer Agent should not be Ready while losing the shared id")
	}

	// The older holder must not be rejected by its own reconcile.
	reconcileAgent(t, r, older)
	gotOlder := getAgent(t, r, "ns-a", "older")
	if gotOlder.Status.Phase == "Failed" {
		t.Errorf("older Agent should own the id, got Failed: %q", gotOlder.Status.Message)
	}

	// Adoption: once the older holder is gone, the newer becomes the holder.
	if err := cl.Delete(context.Background(), older); err != nil {
		t.Fatalf("delete older: %v", err)
	}
	reconcileAgent(t, r, newer)
	gotNewer = getAgent(t, r, "ns-b", "newer")
	if gotNewer.Status.Phase == "Failed" {
		t.Errorf("newer Agent should adopt the id after older is deleted, still Failed: %q", gotNewer.Status.Message)
	}
}

// TestAgentIdentityDistinctIDsNoConflict verifies distinct ids do not collide.
func TestAgentIdentityDistinctIDsNoConflict(t *testing.T) {
	a := agentWithIDAndAge("ns-a", "a", "one", time.Unix(100, 0))
	b := agentWithIDAndAge("ns-b", "b", "two", time.Unix(200, 0))

	cl := fake.NewClientBuilder().
		WithScheme(conflictScheme(t)).
		WithObjects(a, b).
		WithStatusSubresource(a, b).
		Build()
	r := &AgentReconciler{Client: cl, Scheme: conflictScheme(t)}

	reconcileAgent(t, r, b)
	if got := getAgent(t, r, "ns-b", "b"); got.Status.Phase == "Failed" {
		t.Errorf("distinct ids must not conflict, got Failed: %q", got.Status.Message)
	}
}
