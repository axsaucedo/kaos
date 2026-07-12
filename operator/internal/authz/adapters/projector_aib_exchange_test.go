package adapters

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	"github.com/axsaucedo/kaos/operator/internal/projection"
)

type fakeExchangeAIB struct {
	created map[string][]map[string]any
}

func (f *fakeExchangeAIB) Upsert(_ context.Context, collection, _, _ string, body map[string]any) (string, error) {
	f.created[collection] = append(f.created[collection], body)
	return collection + "-id", nil
}

func TestExchangeProjectorAggregatesPermissionSetsPerAgent(t *testing.T) {
	scheme := newTestScheme(t)
	objects := []runtime.Object{
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github-oauth"}, Data: map[string][]byte{"secret": []byte("github-secret")}},
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "drive-oauth"}, Data: map[string][]byte{"secret": []byte("drive-secret")}},
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "kaos-oidc-researcher"}, Data: map[string][]byte{"client_id": []byte("agent-researcher")}},
	}
	admin := &fakeExchangeAIB{created: map[string][]map[string]any{}}
	projector := &ExchangeProjector{Client: fake.NewClientBuilder().WithScheme(scheme).WithRuntimeObjects(objects...).Build(), AIB: admin, Enabled: true}
	service := func(name string) projection.DesiredThirdPartyService {
		return projection.DesiredThirdPartyService{
			Namespace: "demo", Name: name, ClientID: name + "-client", ClientSecretName: name + "-oauth", ClientSecretKey: "secret",
			Scopes: []projection.ThirdPartyScope{{Name: "read"}}, Access: []projection.ThirdPartyAccess{{Agent: "researcher", Scopes: []string{"read"}}},
		}
	}
	desired := projection.DesiredState{ThirdPartyServices: []projection.DesiredThirdPartyService{service("github"), service("drive")}}

	if err := projector.Apply(context.Background(), desired); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if len(admin.created["agents"]) != 1 {
		t.Fatalf("agent upserts = %d, want 1", len(admin.created["agents"]))
	}
	permissionSets := admin.created["agents"][0]["permission_sets"].([]any)
	if len(permissionSets) != 2 {
		t.Fatalf("agent permission sets = %#v", permissionSets)
	}
}

func TestExchangeProjectorProjectsRealServicePermissionSetAndAgent(t *testing.T) {
	scheme := newTestScheme(t)
	providerSecret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github-oauth"},
		Data:       map[string][]byte{"secret": []byte("provider-secret")},
	}
	agentSecret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "kaos-oidc-researcher"},
		Data:       map[string][]byte{"client_id": []byte("agent-researcher")},
	}
	admin := &fakeExchangeAIB{created: map[string][]map[string]any{}}
	projector := &ExchangeProjector{
		Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(providerSecret, agentSecret).Build(),
		AIB:    admin, Enabled: true, OIDCSecretPrefix: "kaos-oidc",
	}
	desired := projection.DesiredState{ThirdPartyServices: []projection.DesiredThirdPartyService{{
		Namespace: "demo", Name: "github", DisplayName: "GitHub", ClientID: "github-client",
		ClientSecretName: "github-oauth", ClientSecretKey: "secret", IssuerURI: "https://github.com",
		TokenEndpoint: "https://github.com/login/oauth/access_token", AuthorizeEndpoint: "https://github.com/login/oauth/authorize",
		Scopes:             []projection.ThirdPartyScope{{Name: "repo", Description: "Read repositories"}},
		ProtectedResources: []string{"https://api.github.com/"},
		Access:             []projection.ThirdPartyAccess{{Agent: "researcher", Scopes: []string{"repo"}}},
	}}}

	if err := projector.Apply(context.Background(), desired); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if len(admin.created["services"]) != 1 || len(admin.created["permission-sets"]) != 1 || len(admin.created["agents"]) != 1 {
		t.Fatalf("created records = %#v", admin.created)
	}
	service := admin.created["services"][0]
	if service["client_id"] != "github-client" || service["client_secret"] != "provider-secret" {
		t.Fatalf("service body = %#v", service)
	}
	permissionSet := admin.created["permission-sets"][0]
	if permissionSet["name"] != "kaos:thirdparty:demo:github:researcher" {
		t.Fatalf("permission set = %#v", permissionSet)
	}
	agent := admin.created["agents"][0]
	if agent["client_id"] != "agent-researcher" || agent["external_id"] != "kaos://agent/demo/researcher" {
		t.Fatalf("agent body = %#v", agent)
	}
}

func TestExchangeProjectorOffProjectsNothing(t *testing.T) {
	admin := &fakeExchangeAIB{created: map[string][]map[string]any{}}
	projector := &ExchangeProjector{AIB: admin, Enabled: false}
	desired := projection.DesiredState{ThirdPartyServices: []projection.DesiredThirdPartyService{{Name: "github"}}}

	if err := projector.Apply(context.Background(), desired); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if len(admin.created) != 0 {
		t.Fatalf("feature-off projection created records: %#v", admin.created)
	}
}

func TestExchangeProjectorRejectsUndeclaredScope(t *testing.T) {
	scheme := newTestScheme(t)
	providerSecret := &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "oauth"}, Data: map[string][]byte{"secret": []byte("value")}}
	admin := &fakeExchangeAIB{created: map[string][]map[string]any{}}
	projector := &ExchangeProjector{Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(providerSecret).Build(), AIB: admin, Enabled: true}
	desired := projection.DesiredState{ThirdPartyServices: []projection.DesiredThirdPartyService{{
		Namespace: "demo", Name: "github", ClientID: "github", ClientSecretName: "oauth", ClientSecretKey: "secret",
		Scopes: []projection.ThirdPartyScope{{Name: "read"}}, Access: []projection.ThirdPartyAccess{{Agent: "researcher", Scopes: []string{"write"}}},
	}}}

	if err := projector.Apply(context.Background(), desired); err == nil {
		t.Fatal("expected undeclared scope error")
	}
	if len(admin.created["permission-sets"]) != 0 || len(admin.created["agents"]) != 0 {
		t.Fatalf("invalid binding projected: %#v", admin.created)
	}
}
