package controllers

import (
	"context"
	"reflect"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/aib"
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

// fakeAIB is an in-memory AIBAdmin recording created records and minted creds.
type fakeAIB struct {
	created map[string][]string
	minted  int
}

func newFakeAIB() *fakeAIB { return &fakeAIB{created: map[string][]string{}} }

func (f *fakeAIB) List(context.Context, string) ([]map[string]any, error) { return nil, nil }

func (f *fakeAIB) CreateOrGet(_ context.Context, collection, _, matchValue string, _ map[string]any) (string, error) {
	f.created[collection] = append(f.created[collection], matchValue)
	return collection + ":" + matchValue, nil
}

func (f *fakeAIB) Delete(context.Context, string, string) (bool, error) { return false, nil }

func (f *fakeAIB) MintCredentials(context.Context, string) (aib.Credentials, error) {
	f.minted++
	return aib.Credentials{ClientID: "cid", ClientSecret: "secret"}, nil
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

func TestProjectionReconcileMintsCredentialSecret(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}, ModelAPI: "gpt"},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	admin := newFakeAIB()
	r := &AIBProjectionReconciler{Client: c, AIB: admin, SecretPrefix: "kaos-aib", Prune: false}

	if _, err := r.Reconcile(context.Background(), aibSentinel); err != nil {
		t.Fatalf("reconcile: %v", err)
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
	// Second pass must not re-mint once the secret carries a client_id.
	provisioned := secret.DeepCopy()
	provisioned.Data = map[string][]byte{"client_id": []byte("cid")}
	if err := c.Update(context.Background(), provisioned); err != nil {
		t.Fatalf("seed provisioned secret: %v", err)
	}
	if _, err := r.Reconcile(context.Background(), aibSentinel); err != nil {
		t.Fatalf("second reconcile: %v", err)
	}
	if admin.minted != 1 {
		t.Fatalf("re-minted on second pass: minted = %d", admin.minted)
	}
}

var _ client.Client = fake.NewClientBuilder().Build()

var _ reconcile.Reconciler = (*AIBProjectionReconciler)(nil)
