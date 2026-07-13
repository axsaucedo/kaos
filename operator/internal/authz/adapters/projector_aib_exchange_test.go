package adapters

import (
	"context"
	"reflect"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
)

type fakeExchangeAIB struct {
	updates []map[string]any
}

func (f *fakeExchangeAIB) List(context.Context, string) ([]map[string]any, error) {
	return nil, nil
}

func (f *fakeExchangeAIB) ListAgents(context.Context) ([]map[string]any, error) {
	return nil, nil
}

func (f *fakeExchangeAIB) Update(_ context.Context, _, _ string, body map[string]any) error {
	f.updates = append(f.updates, body)
	return nil
}

func TestBuildReflectionIncludesOnlyAIBBoundKAOSAgents(t *testing.T) {
	serviceID := "19d8e478-9682-489d-84a0-5f70b5d2bd9a"
	permissionID := "28d4b51c-db18-4bfb-bed1-af658629c47c"
	desired := map[string]projection.DesiredAgent{
		"kaos/demo/researcher": {Namespace: "demo", Name: "researcher"},
		"kaos/demo/unbound":    {Namespace: "demo", Name: "unbound"},
	}
	agents := []map[string]any{
		{"external_id": "kaos/demo/researcher", "permission_sets": []any{map[string]any{"permission_set_id": permissionID}}},
		{"external_id": "someone-else", "permission_sets": []any{map[string]any{"permission_set_id": permissionID}}},
	}
	services := []map[string]any{{"id": serviceID, "protected_resources": []any{"https://uploads.example/api", "https://api.example/data"}}}
	permissionSets := []map[string]any{{"id": permissionID, "service_scopes": []any{map[string]any{"service_id": serviceID}}}}

	state, err := buildReflection(desired, agents, services, permissionSets)
	if err != nil {
		t.Fatalf("buildReflection: %v", err)
	}
	want := []string{"https://api.example/data", "https://uploads.example/api"}
	if got := state["demo"].Targets["researcher"]; !reflect.DeepEqual(got, want) {
		t.Fatalf("researcher targets = %#v, want %#v", got, want)
	}
	if _, exists := state["demo"].Targets["unbound"]; exists {
		t.Fatal("unbound Agent received token-exchange targets")
	}
	if len(state["demo"].Services[serviceID].Origins) != 2 {
		t.Fatalf("service origins = %#v", state["demo"].Services[serviceID].Origins)
	}
}

func TestRefreshAgentIDsMigratesLegacyNameAndPreservesBindings(t *testing.T) {
	scheme := newTestScheme(t)
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "kaos-oidc-researcher"},
		Data:       map[string][]byte{"client_id": []byte("current-dcr-uuid")},
	}
	admin := &fakeExchangeAIB{}
	projector := &ExchangeProjector{
		Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(secret).Build(),
		AIB:    admin,
	}
	record := map[string]any{
		"id": "agent-id", "external_id": "kaos://agent/demo/researcher", "client_id": "stale-dcr-uuid",
		"display_name": "Researcher", "description": "admin description",
		"permission_sets": []any{map[string]any{"permission_set_id": "permission-id", "requirement_type": "mandatory"}},
	}
	desired := map[string]projection.DesiredAgent{"kaos/demo/researcher": {Namespace: "demo", Name: "researcher"}}

	if err := projector.refreshAgentIDs(context.Background(), desired, []map[string]any{record}); err != nil {
		t.Fatalf("refreshAgentIDs: %v", err)
	}
	if len(admin.updates) != 1 {
		t.Fatalf("updates = %d, want 1", len(admin.updates))
	}
	update := admin.updates[0]
	if update["external_id"] != "kaos/demo/researcher" || update["client_id"] != "current-dcr-uuid" {
		t.Fatalf("identity update = %#v", update)
	}
	if !reflect.DeepEqual(update["permission_sets"], record["permission_sets"]) {
		t.Fatalf("permission sets changed: %#v", update["permission_sets"])
	}
}

func TestGeneratedEgressUsesFQDNBackendAndTLSOrigination(t *testing.T) {
	origin := exchangeOrigin{Scheme: "https", Hostname: "api.example.com", Port: 443}
	backend := constructExchangeBackend("demo", "service-id", origin, "kaos-egress-test")
	tls, found, err := unstructuredNestedMap(backend.Object, "spec", "tls")
	if err != nil || !found || tls["wellKnownCACertificates"] != "System" {
		t.Fatalf("backend TLS = %#v, found=%v err=%v", tls, found, err)
	}
	route := constructExchangeRoute("demo", "service-id", origin, "kaos-egress-test", gateway.Config{GatewayName: "kaos-gateway", GatewayNamespace: "kaos-system"})
	if len(route.Spec.Hostnames) != 1 || route.Spec.Hostnames[0] != "api.example.com" {
		t.Fatalf("route hostnames = %#v", route.Spec.Hostnames)
	}
	ref := route.Spec.Rules[0].BackendRefs[0].BackendRef.BackendObjectReference
	if ref.Group == nil || *ref.Group != extensionPolicyGroup || ref.Kind == nil || *ref.Kind != backendKind {
		t.Fatalf("backendRef = %#v", ref)
	}
}

func TestExtProcTargetsOnlyOperatorGeneratedEgressRoutes(t *testing.T) {
	generated := &gatewayv1.HTTPRoute{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "egress", Labels: managedRouteLabels("service-id")}}
	policy, err := constructExtProcPolicy(generated, "extproc", "aib-system", 50051)
	if err != nil {
		t.Fatalf("generated route rejected: %v", err)
	}
	targets, _, _ := unstructuredNestedSlice(policy.Object, "spec", "targetRefs")
	if targets[0].(map[string]any)["name"] != "egress" {
		t.Fatalf("targetRefs = %#v", targets)
	}

	for _, kind := range []string{"Agent", "MCPServer", "ModelAPI", "MemoryStore"} {
		t.Run(kind, func(t *testing.T) {
			internal := &gatewayv1.HTTPRoute{ObjectMeta: metav1.ObjectMeta{
				Namespace: "demo", Name: "internal",
				OwnerReferences: []metav1.OwnerReference{{APIVersion: "kaos.tools/v1alpha1", Kind: kind, Name: "internal"}},
			}}
			if policy, err := constructExtProcPolicy(internal, "extproc", "aib-system", 50051); err == nil || policy != nil {
				t.Fatalf("internal route accepted: policy=%#v err=%v", policy, err)
			}
		})
	}
}

func unstructuredNestedMap(object map[string]any, fields ...string) (map[string]any, bool, error) {
	current := any(object)
	for _, field := range fields {
		mapping, ok := current.(map[string]any)
		if !ok {
			return nil, false, nil
		}
		current, ok = mapping[field]
		if !ok {
			return nil, false, nil
		}
	}
	value, ok := current.(map[string]any)
	return value, ok, nil
}

func unstructuredNestedSlice(object map[string]any, fields ...string) ([]any, bool, error) {
	current := any(object)
	for _, field := range fields {
		mapping, ok := current.(map[string]any)
		if !ok {
			return nil, false, nil
		}
		current, ok = mapping[field]
		if !ok {
			return nil, false, nil
		}
	}
	value, ok := current.([]any)
	return value, ok, nil
}
