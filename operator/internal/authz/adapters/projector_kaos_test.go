package adapters

import (
	"context"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

func TestConfigMapProjectorWritesPolicyConfigMap(t *testing.T) {
	scheme := newTestScheme(t)
	mcp := &kaosv1alpha1.MCPServer{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github"}}
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(mcp, agent).Build()
	p := &ConfigMapProjector{Client: c, Name: "kaos-authz-policy", Namespace: "aib-system", WriteGrantData: true}
	desired := projection.Project([]projection.Resource{resourceFromAgent(agent), {
		Kind: projection.MCPServer.ResourceKind, Namespace: "demo", Name: "github",
	}})

	if err := p.Apply(context.Background(), desired); err != nil {
		t.Fatalf("apply: %v", err)
	}

	cm := &corev1.ConfigMap{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "aib-system", Name: "kaos-authz-policy"}, cm); err != nil {
		t.Fatalf("expected policy ConfigMap: %v", err)
	}
	if _, ok := cm.Data["policy.rego"]; !ok {
		t.Fatalf("ConfigMap missing policy.rego: %v", cm.Data)
	}
	data, ok := cm.Data["data.json"]
	if !ok {
		t.Fatalf("ConfigMap missing data.json")
	}
	if !contains(data, "kaos://agent/demo/researcher") || !contains(data, "kaos://mcpserver/demo/github") {
		t.Fatalf("data.json missing expected grant: %s", data)
	}
}

func TestConfigMapProjectorSkipsPolicyConfigMapWhenUnset(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	p := &ConfigMapProjector{Client: c}

	if err := p.Apply(context.Background(), projection.Project([]projection.Resource{resourceFromAgent(agent)})); err != nil {
		t.Fatalf("apply: %v", err)
	}
	cmList := &corev1.ConfigMapList{}
	if err := c.List(context.Background(), cmList); err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(cmList.Items) != 0 {
		t.Fatalf("expected no ConfigMap written, got %d", len(cmList.Items))
	}
}

func TestConfigMapProjectorInjectsJWKSInVerifiedMode(t *testing.T) {
	jwksBody := `{"keys":[{"kty":"RSA","kid":"k1","n":"abc","e":"AQAB"}]}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(jwksBody))
	}))
	defer srv.Close()

	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}},
	}
	mcp := &kaosv1alpha1.MCPServer{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github"}}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent, mcp).Build()
	p := &ConfigMapProjector{Client: c, Name: "kaos-authz-policy", Namespace: "aib-system", JWKSURI: srv.URL, WriteGrantData: true}
	desired := projection.Project([]projection.Resource{resourceFromAgent(agent), {
		Kind: projection.MCPServer.ResourceKind, Namespace: "demo", Name: "github",
	}})

	if err := p.Apply(context.Background(), desired); err != nil {
		t.Fatalf("apply: %v", err)
	}
	cm := &corev1.ConfigMap{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "aib-system", Name: "kaos-authz-policy"}, cm); err != nil {
		t.Fatalf("expected policy ConfigMap: %v", err)
	}
	if !contains(cm.Data["data.json"], "\"jwks\"") || !contains(cm.Data["data.json"], "\"kid\": \"k1\"") {
		t.Fatalf("data.json missing injected jwks: %s", cm.Data["data.json"])
	}
}

func contains(s, sub string) bool {
	return strings.Contains(s, sub)
}

func TestConfigMapProjectorLeavesBYOConfigMapUntouched(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}},
	}
	byo := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Namespace: "aib-system", Name: "kaos-authz-policy"},
		Data: map[string]string{
			"policy.rego": "package admin.owned\n",
			"data.json":   `{"kaos":{"grants":{"admin":["x"]}}}`,
		},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent, byo).Build()
	p := &ConfigMapProjector{Client: c}

	if err := p.Apply(context.Background(), projection.Project([]projection.Resource{resourceFromAgent(agent)})); err != nil {
		t.Fatalf("apply: %v", err)
	}
	got := &corev1.ConfigMap{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "aib-system", Name: "kaos-authz-policy"}, got); err != nil {
		t.Fatalf("get: %v", err)
	}
	if !reflect.DeepEqual(got.Data, byo.Data) {
		t.Fatalf("operator clobbered admin ConfigMap: %v", got.Data)
	}
}

func TestConfigMapProjectorRegoOverrideLeavesAdminDataUntouched(t *testing.T) {
	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher"},
		Spec:       kaosv1alpha1.AgentSpec{MCPServers: []string{"github"}},
	}
	adminData := `{"kaos":{"grants":{"kaos://agent/demo/researcher":["kaos://mcpserver/demo/other"]}}}`
	adminCM := &corev1.ConfigMap{
		TypeMeta:   metav1.TypeMeta{APIVersion: "v1", Kind: "ConfigMap"},
		ObjectMeta: metav1.ObjectMeta{Namespace: "aib-system", Name: "kaos-authz-policy"},
		Data:       map[string]string{"data.json": adminData},
	}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	if err := c.Patch(context.Background(), adminCM, client.Apply, client.FieldOwner("admin")); err != nil {
		t.Fatalf("admin apply: %v", err)
	}
	p := &ConfigMapProjector{Client: c, Name: "kaos-authz-policy", Namespace: "aib-system", WriteGrantData: false}
	desired := projection.Project([]projection.Resource{resourceFromAgent(agent)})

	for i := 0; i < 2; i++ {
		if err := p.Apply(context.Background(), desired); err != nil {
			t.Fatalf("apply %d: %v", i, err)
		}
	}

	got := &corev1.ConfigMap{}
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "aib-system", Name: "kaos-authz-policy"}, got); err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Data["policy.rego"] == "" {
		t.Fatalf("operator did not write policy.rego: %v", got.Data)
	}
	if got.Data["data.json"] != adminData {
		t.Fatalf("operator clobbered admin-authored data.json: %q", got.Data["data.json"])
	}
}
