package controllers

import (
	"context"
	"reflect"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

func TestResourceFromAgentMapsSpec(t *testing.T) {
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "a"},
		Spec: kaosv1alpha1.AgentSpec{
			MCPServers:   []string{"github"},
			ModelAPI:     "gpt",
			AgentNetwork: &kaosv1alpha1.AgentNetworkConfig{Access: []string{"b", "c"}},
		},
	}

	res := resourceFromAgent(agent)

	if res.Kind != "Agent" || res.Namespace != "demo" || res.Name != "a" {
		t.Fatalf("identity = %+v", res)
	}
	if !reflect.DeepEqual(res.MCPServers, []string{"github"}) {
		t.Fatalf("mcpServers = %v", res.MCPServers)
	}
	if res.ModelAPI != "gpt" {
		t.Fatalf("modelAPI = %q", res.ModelAPI)
	}
	if !reflect.DeepEqual(res.Access, []string{"b", "c"}) {
		t.Fatalf("access = %v", res.Access)
	}
}

func TestResourceFromAgentWithoutNetworkHasNoAccess(t *testing.T) {
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "a"},
		Spec:       kaosv1alpha1.AgentSpec{ModelAPI: "gpt"},
	}
	if res := resourceFromAgent(agent); len(res.Access) != 0 {
		t.Fatalf("access = %v, want empty", res.Access)
	}
}

func TestProjectionReconcileDispatchesDesiredState(t *testing.T) {
	scheme := newTestScheme(t)
	mcp := &kaosv1alpha1.MCPServer{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github"}}
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}},
	}
	projector := &fakeProjector{}
	r := &AuthzProjectionReconciler{
		Client:    fake.NewClientBuilder().WithScheme(scheme).WithObjects(mcp, agent).Build(),
		Scheme:    scheme,
		Projector: projector,
	}

	if _, err := r.Reconcile(context.Background(), authzSentinel); err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if projector.calls != 1 {
		t.Fatalf("projector calls = %d, want 1", projector.calls)
	}
	if len(projector.desired.Agents) != 1 || projector.desired.Agents[0].ExternalID() != "kaos://agent/demo/researcher" {
		t.Fatalf("agents = %+v", projector.desired.Agents)
	}
	if len(projector.desired.Services) != 1 || projector.desired.Services[0].ClientID() != "kaos-mcpserver-demo-github" {
		t.Fatalf("services = %+v", projector.desired.Services)
	}
}

var _ client.Client = fake.NewClientBuilder().Build()
var _ reconcile.Reconciler = (*AuthzProjectionReconciler)(nil)

func newTestScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatalf("clientgo scheme: %v", err)
	}
	if err := kaosv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("kaos scheme: %v", err)
	}
	return scheme
}

type fakeProjector struct {
	calls   int
	desired projection.DesiredState
}

func (f *fakeProjector) Apply(_ context.Context, desired projection.DesiredState) error {
	f.calls++
	f.desired = desired
	return nil
}
