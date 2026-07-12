package controllers

import (
	"context"
	"reflect"
	"strings"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/tools/record"
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
			Config: &kaosv1alpha1.AgentConfig{
				Memory: &kaosv1alpha1.MemoryConfig{MemoryStore: "brain"},
			},
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
	if res.MemoryStore != "brain" {
		t.Fatalf("memoryStore = %q", res.MemoryStore)
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

func TestResourceFromAgentDerivesAutonomousFromGoal(t *testing.T) {
	tests := []struct {
		name       string
		autonomous *kaosv1alpha1.AutonomousConfig
		want       bool
	}{
		{name: "goal", autonomous: &kaosv1alpha1.AutonomousConfig{Goal: "Investigate"}, want: true},
		{name: "blank goal", autonomous: &kaosv1alpha1.AutonomousConfig{Goal: "  "}},
		{name: "plain agent"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			agent := &kaosv1alpha1.Agent{}
			if tt.autonomous != nil {
				agent.Spec.Config = &kaosv1alpha1.AgentConfig{Autonomous: tt.autonomous}
			}
			if got := resourceFromAgent(agent).Autonomous; got != tt.want {
				t.Fatalf("Autonomous = %v, want %v", got, tt.want)
			}
		})
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
		Client:     fake.NewClientBuilder().WithScheme(scheme).WithObjects(mcp, agent).Build(),
		Scheme:     scheme,
		Projectors: []PolicyProjector{projector},
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

func TestProjectionReconcileDispatchesToAllProjectors(t *testing.T) {
	scheme := newTestScheme(t)
	first, second := &fakeProjector{}, &fakeProjector{}
	r := &AuthzProjectionReconciler{
		Client:     fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme:     scheme,
		Projectors: []PolicyProjector{first, second},
	}
	if _, err := r.Reconcile(context.Background(), authzSentinel); err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if first.calls != 1 || second.calls != 1 {
		t.Fatalf("projector calls = %d/%d, want 1/1", first.calls, second.calls)
	}
}

func TestProjectionReconcileMarksAccessGrantUnenforcedAndSkipsProjection(t *testing.T) {
	scheme := newTestScheme(t)
	grant := &kaosv1alpha1.AccessGrant{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "users"},
		Spec: kaosv1alpha1.AccessGrantSpec{
			Subjects:  []kaosv1alpha1.AccessGrantSubject{{Kind: kaosv1alpha1.AccessGrantSubjectKindUser, Name: "alice"}},
			Resources: []kaosv1alpha1.AccessGrantResource{{Kind: kaosv1alpha1.AccessGrantResourceKindAgent, Name: "a"}},
		},
	}
	projector := &fakeProjector{}
	recorder := record.NewFakeRecorder(1)
	c := fake.NewClientBuilder().WithScheme(scheme).WithStatusSubresource(grant).WithObjects(grant).Build()
	r := &AuthzProjectionReconciler{Client: c, Scheme: scheme, Projectors: []PolicyProjector{projector}, Recorder: recorder}

	if _, err := r.Reconcile(context.Background(), authzSentinel); err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if len(projector.desired.AccessGrants) != 0 {
		t.Fatalf("projected AccessGrants = %v, want none", projector.desired.AccessGrants)
	}
	updated := &kaosv1alpha1.AccessGrant{}
	if err := c.Get(context.Background(), client.ObjectKeyFromObject(grant), updated); err != nil {
		t.Fatalf("get AccessGrant: %v", err)
	}
	condition := updated.Status.Conditions[0]
	if condition.Type != "Enforced" || condition.Status != metav1.ConditionFalse || condition.Reason != "NoUserIdentityProvider" {
		t.Fatalf("condition = %+v", condition)
	}
	select {
	case event := <-recorder.Events:
		if !strings.Contains(event, "NoUserIdentityProvider") {
			t.Fatalf("event = %q", event)
		}
	default:
		t.Fatal("expected warning event")
	}
}

func TestProjectionReconcileMarksAccessGrantEnforcedAndProjectsIt(t *testing.T) {
	scheme := newTestScheme(t)
	grant := &kaosv1alpha1.AccessGrant{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "users"},
		Spec: kaosv1alpha1.AccessGrantSpec{
			Subjects:  []kaosv1alpha1.AccessGrantSubject{{Kind: kaosv1alpha1.AccessGrantSubjectKindGroup, Name: "editors"}},
			Resources: []kaosv1alpha1.AccessGrantResource{{Kind: kaosv1alpha1.AccessGrantResourceKindAgent, Name: "a"}},
		},
	}
	projector := &fakeProjector{}
	c := fake.NewClientBuilder().WithScheme(scheme).WithStatusSubresource(grant).WithObjects(grant).Build()
	r := &AuthzProjectionReconciler{Client: c, Scheme: scheme, Projectors: []PolicyProjector{projector}, UserIssuer: "https://users.example"}

	if _, err := r.Reconcile(context.Background(), authzSentinel); err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if len(projector.desired.AccessGrants) != 1 {
		t.Fatalf("projected AccessGrants = %v", projector.desired.AccessGrants)
	}
	updated := &kaosv1alpha1.AccessGrant{}
	if err := c.Get(context.Background(), client.ObjectKeyFromObject(grant), updated); err != nil {
		t.Fatalf("get AccessGrant: %v", err)
	}
	condition := updated.Status.Conditions[0]
	if condition.Status != metav1.ConditionTrue || condition.Reason != "Enforced" {
		t.Fatalf("condition = %+v", condition)
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
