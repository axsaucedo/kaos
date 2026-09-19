package adapters

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/aib"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

// fakeAIB is an in-memory AIBAdmin recording created records and minted creds.
type fakeAIB struct {
	created map[string][]string
	listed  map[string][]map[string]any
	minted  int
	deleted int
	bodies  []map[string]any
}

func newFakeAIB() *fakeAIB {
	return &fakeAIB{created: map[string][]string{}, listed: map[string][]map[string]any{}}
}

func (f *fakeAIB) ListAgents(context.Context) ([]map[string]any, error) {
	return f.listed["agents"], nil
}

func (f *fakeAIB) List(_ context.Context, collection string) ([]map[string]any, error) {
	return f.listed[collection], nil
}

func (f *fakeAIB) UpsertAgent(_ context.Context, externalID string, body map[string]any) (string, error) {
	f.created["agents"] = append(f.created["agents"], externalID)
	f.bodies = append(f.bodies, body)
	return "agents:" + externalID, nil
}

func (f *fakeAIB) DeleteAgent(context.Context, string) (bool, error) {
	f.deleted++
	return true, nil
}

func (f *fakeAIB) MintCredentials(context.Context, string) (aib.Credentials, error) {
	f.minted++
	return aib.Credentials{ClientID: "cid", ClientSecret: "secret"}, nil
}

func TestBrokerProjectorMintsCredentialSecret(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}, ModelAPI: "gpt"},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	admin := newFakeAIB()
	p := &BrokerProjector{Client: c, Scheme: scheme, AIB: admin, SecretPrefix: "kaos-aib"}
	desired := projection.Project([]projection.Resource{resourceFromAgent(agent)})

	if err := p.Apply(context.Background(), desired); err != nil {
		t.Fatalf("apply: %v", err)
	}

	if admin.minted != 1 {
		t.Fatalf("minted = %d, want 1", admin.minted)
	}
	secret := &corev1.Secret{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "demo", Name: "kaos-aib-researcher"}, secret); err != nil {
		t.Fatalf("expected credential secret: %v", err)
	}
	if secret.StringData["client_id"] != "cid" {
		t.Fatalf("client_id = %q", secret.StringData["client_id"])
	}
	if len(secret.OwnerReferences) != 1 {
		t.Fatalf("owner references = %d, want 1", len(secret.OwnerReferences))
	}
	owner := secret.OwnerReferences[0]
	if owner.Kind != "Agent" || owner.Name != "researcher" || owner.Controller == nil || !*owner.Controller {
		t.Fatalf("unexpected owner reference: %+v", owner)
	}
	provisioned := secret.DeepCopy()
	provisioned.Data = map[string][]byte{"client_id": []byte("cid")}
	if err := c.Update(context.Background(), provisioned); err != nil {
		t.Fatalf("seed provisioned secret: %v", err)
	}
	if err := p.Apply(context.Background(), desired); err != nil {
		t.Fatalf("second apply: %v", err)
	}
	if admin.minted != 1 {
		t.Fatalf("re-minted on second pass: minted = %d", admin.minted)
	}
}

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

func resourceFromAgent(a *kaosv1alpha1.Agent) projection.Resource {
	res := projection.Resource{
		Kind:       projection.AgentKind,
		Namespace:  a.Namespace,
		Name:       a.Name,
		MCPServers: a.Spec.MCPServers,
		ModelAPI:   a.Spec.ModelAPI,
	}
	if a.Spec.AgentNetwork != nil {
		res.Access = a.Spec.AgentNetwork.Access
	}
	if a.Spec.Config != nil && a.Spec.Config.Memory != nil {
		res.MemoryStore = a.Spec.Config.Memory.MemoryStore
	}
	return res
}

func TestAgentBodyContainsIdentityOnly(t *testing.T) {
	agent := projection.DesiredAgent{Namespace: "demo", Name: "researcher"}
	body := AgentBody(agent, "")
	if _, leaks := body["client_id"]; leaks {
		t.Fatalf("agent body leaks client_id: %v", body)
	}
	if body["display_name"] != agent.ExternalID() {
		t.Fatalf("display_name = %v", body["display_name"])
	}
	if _, projects := body["permission_sets"]; projects {
		t.Fatalf("agent body projects permission sets: %v", body)
	}
}

func TestAdminBodiesCarryNoApprovalStatus(t *testing.T) {
	approvalKeys := map[string]bool{"approved": true, "approval": true, "status": true, "state": true, "decision": true, "granted": true}
	check := func(body map[string]any, where string) {
		for k := range body {
			if approvalKeys[k] {
				t.Fatalf("%s leaks approval key %q", where, k)
			}
		}
	}

	agent := projection.DesiredAgent{Namespace: "demo", Name: "researcher"}

	body := AgentBody(agent, "")
	check(body, "agent body")
}

func TestBrokerProjectorAddsConfiguredPermissionSet(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"}}
	c := fake.NewClientBuilder().WithScheme(scheme).WithStatusSubresource(agent).WithObjects(agent).Build()
	admin := newFakeAIB()
	admin.listed["permission-sets"] = []map[string]any{{"id": "permission-set-1", "name": "kaos-identity"}}
	p := &BrokerProjector{Client: c, Scheme: scheme, AIB: admin, SecretPrefix: "kaos-aib", DefaultPermissionSet: "kaos-identity"}
	desired := projection.DesiredState{Agents: []projection.DesiredAgent{{Namespace: "demo", Name: "researcher"}}}

	if err := p.Apply(context.Background(), desired); err != nil {
		t.Fatalf("apply: %v", err)
	}
	entries, ok := admin.bodies[0]["permission_sets"].([]map[string]any)
	if !ok || len(entries) != 1 || entries[0]["permission_set_id"] != "permission-set-1" || entries[0]["requirement_type"] != "mandatory" {
		t.Fatalf("permission_sets = %#v", admin.bodies[0]["permission_sets"])
	}
}

func TestBrokerProjectorBlocksRegistrationWhenPermissionSetMissing(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher", Generation: 2}}
	c := fake.NewClientBuilder().WithScheme(scheme).WithStatusSubresource(agent).WithObjects(agent).Build()
	admin := newFakeAIB()
	p := &BrokerProjector{Client: c, Scheme: scheme, AIB: admin, DefaultPermissionSet: "kaos-identity"}
	desired := projection.DesiredState{Agents: []projection.DesiredAgent{{Namespace: "demo", Name: "researcher"}}}

	if err := p.Apply(context.Background(), desired); err == nil {
		t.Fatal("expected missing permission set to fail")
	}
	if len(admin.created["agents"]) != 0 {
		t.Fatalf("registered agents = %v", admin.created["agents"])
	}
	updated := &kaosv1alpha1.Agent{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "demo", Name: "researcher"}, updated); err != nil {
		t.Fatalf("get Agent: %v", err)
	}
	condition := meta.FindStatusCondition(updated.Status.Conditions, identityProvisioningDegradedCondition)
	if condition == nil || condition.Status != metav1.ConditionTrue || condition.Reason != "DefaultPermissionSetUnavailable" {
		t.Fatalf("condition = %#v", condition)
	}
}

func TestBrokerProjectorProjectsIdentityOnly(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}, ModelAPI: "gpt"},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	admin := newFakeAIB()
	p := &BrokerProjector{Client: c, Scheme: scheme, AIB: admin, SecretPrefix: "kaos-aib", Prune: true}
	desired := projection.Project([]projection.Resource{resourceFromAgent(agent), {
		Kind: projection.MCPServer.ResourceKind, Namespace: "demo", Name: "github",
	}})

	if err := p.Apply(context.Background(), desired); err != nil {
		t.Fatalf("apply: %v", err)
	}

	if admin.minted != 1 {
		t.Fatalf("minted = %d, want 1", admin.minted)
	}
	if len(admin.created["agents"]) != 1 {
		t.Fatalf("agents created = %v, want 1", admin.created["agents"])
	}
	secret := &corev1.Secret{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "demo", Name: "kaos-aib-researcher"}, secret); err != nil {
		t.Fatalf("expected credential secret: %v", err)
	}
	if len(admin.created["services"]) != 0 || len(admin.created["permission-sets"]) != 0 {
		t.Fatalf("authorization projected to broker: services=%v permission-sets=%v",
			admin.created["services"], admin.created["permission-sets"])
	}
}

func TestBrokerProjectorPrunesStaleAgentsOnly(t *testing.T) {
	scheme := newTestScheme(t)
	admin := newFakeAIB()
	admin.listed["agents"] = []map[string]any{{"id": "agent-stale", "display_name": "kaos://agent/demo/stale"}}
	p := &BrokerProjector{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(), Scheme: scheme, AIB: admin,
		SecretPrefix: "kaos-aib", Prune: true,
	}
	if err := p.Apply(context.Background(), projection.DesiredState{}); err != nil {
		t.Fatalf("apply: %v", err)
	}
	if admin.deleted != 1 {
		t.Fatalf("deleted = %d, want one stale agent", admin.deleted)
	}
}
