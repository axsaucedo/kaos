package adapters

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
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
}

func newFakeAIB() *fakeAIB {
	return &fakeAIB{created: map[string][]string{}, listed: map[string][]map[string]any{}}
}

func (f *fakeAIB) List(_ context.Context, collection string) ([]map[string]any, error) {
	return f.listed[collection], nil
}

func (f *fakeAIB) CreateOrGet(_ context.Context, collection, _, matchValue string, _ map[string]any) (string, error) {
	f.created[collection] = append(f.created[collection], matchValue)
	return collection + ":" + matchValue, nil
}

func (f *fakeAIB) Delete(context.Context, string, string) (bool, error) {
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
	p := &BrokerProjector{Client: c, Scheme: scheme, AIB: admin, SecretPrefix: "kaos-aib", Prune: false, BindPermissionSets: true}
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
	return res
}

func TestServiceBodyShape(t *testing.T) {
	svc := projection.DesiredService{Namespace: "demo", Name: "github", Kind: projection.MCPServer}
	body := ServiceBody(svc)
	if body["client_id"] != "kaos-mcpserver-demo-github" {
		t.Fatalf("svc client_id = %v", body["client_id"])
	}
	if body["issuer_uri"] != "https://kaos.local/mcpserver/demo/github" {
		t.Fatalf("issuer_uri = %v", body["issuer_uri"])
	}
	scopes := body["scopes"].([]any)[0].(map[string]any)
	if scopes["scope_value"] != projection.CallScope {
		t.Fatalf("scope_value = %v", scopes["scope_value"])
	}
}

func TestPermissionSetBodyReferencesService(t *testing.T) {
	ps := projection.DesiredPermissionSet{Namespace: "demo", Target: "github", Kind: projection.MCPServer}
	body := PermissionSetBody(ps, "svc-123")
	scopes := body["service_scopes"].([]any)[0].(map[string]any)
	if scopes["service_id"] != "svc-123" {
		t.Fatalf("service_id = %v", scopes["service_id"])
	}
	if scopes["requirement_type"] != "mandatory" {
		t.Fatalf("requirement_type = %v", scopes["requirement_type"])
	}
}

func TestAgentBodyBindsPermissionSetsWithoutLeakingClientID(t *testing.T) {
	agent := projection.DesiredAgent{Namespace: "demo", Name: "researcher"}
	body := AgentBody(agent, []string{"ps-1"})
	if _, leaks := body["client_id"]; leaks {
		t.Fatalf("agent body leaks client_id: %v", body)
	}
	if body["display_name"] != agent.ExternalID() {
		t.Fatalf("display_name = %v", body["display_name"])
	}
	entry := body["permission_sets"].([]any)[0].(map[string]any)
	if entry["permission_set_id"] != "ps-1" || entry["requirement_type"] != "mandatory" {
		t.Fatalf("binding = %v", entry)
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

	svc := projection.DesiredService{Namespace: "demo", Name: "github", Kind: projection.MCPServer}
	ps := projection.DesiredPermissionSet{Namespace: "demo", Target: "github", Kind: projection.MCPServer}
	agent := projection.DesiredAgent{Namespace: "demo", Name: "researcher"}

	check(ServiceBody(svc), "service body")
	check(PermissionSetBody(ps, "svc-id"), "permission-set body")
	body := AgentBody(agent, []string{"ps-id"})
	check(body, "agent body")
	for _, e := range body["permission_sets"].([]any) {
		entry := e.(map[string]any)
		if len(entry) != 2 || entry["requirement_type"] != "mandatory" {
			t.Fatalf("binding entry = %v", entry)
		}
	}
}

func TestBrokerProjectorExternalOffSwitchProjectsIdentityOnly(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}, ModelAPI: "gpt"},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	admin := newFakeAIB()
	p := &BrokerProjector{Client: c, Scheme: scheme, AIB: admin, SecretPrefix: "kaos-aib", Prune: true, BindPermissionSets: false}
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
		t.Fatalf("authorization projected in off-switch: services=%v permission-sets=%v",
			admin.created["services"], admin.created["permission-sets"])
	}
	if admin.deleted != 0 {
		t.Fatalf("prune deleted %d records in off-switch mode", admin.deleted)
	}
}

func TestBrokerProjectorPruneIsGatedByAuthorizationProjection(t *testing.T) {
	staleService := map[string]any{"id": "svc-stale", "client_id": "kaos-mcpserver-demo-stale"}

	t.Run("automated broker mode prunes stale records", func(t *testing.T) {
		scheme := newTestScheme(t)
		admin := newFakeAIB()
		admin.listed["services"] = []map[string]any{staleService}
		p := &BrokerProjector{
			Client: fake.NewClientBuilder().WithScheme(scheme).Build(), Scheme: scheme, AIB: admin,
			SecretPrefix: "kaos-aib", Prune: true, BindPermissionSets: true,
		}

		if err := p.Apply(context.Background(), projection.DesiredState{}); err != nil {
			t.Fatalf("apply: %v", err)
		}
		if admin.deleted == 0 {
			t.Fatal("expected prune to delete the stale record in automated mode")
		}
	})

	t.Run("external off-switch never prunes even with prune enabled", func(t *testing.T) {
		scheme := newTestScheme(t)
		admin := newFakeAIB()
		admin.listed["services"] = []map[string]any{staleService}
		p := &BrokerProjector{
			Client: fake.NewClientBuilder().WithScheme(scheme).Build(), Scheme: scheme, AIB: admin,
			SecretPrefix: "kaos-aib", Prune: true, BindPermissionSets: false,
		}

		if err := p.Apply(context.Background(), projection.DesiredState{}); err != nil {
			t.Fatalf("apply: %v", err)
		}
		if admin.deleted != 0 {
			t.Fatalf("prune deleted %d records despite the off-switch", admin.deleted)
		}
	})
}
