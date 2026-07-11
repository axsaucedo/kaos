package authz

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestPolicyEmbedsRego(t *testing.T) {
	p := Policy()
	if !strings.Contains(p, "package "+PolicyPackage) {
		t.Fatalf("policy missing package %q: %q", PolicyPackage, p)
	}
	if !strings.Contains(p, "data.kaos.grants") || !strings.Contains(p, "data.kaos.jwks") {
		t.Fatalf("policy does not reference the expected data documents")
	}
}

func TestDataDocumentDemoModeOmitsJWKS(t *testing.T) {
	grants := map[string][]string{"kaos://agent/demo/researcher": {"kaos://mcpserver/demo/github"}}
	raw, err := DataDocument(grants, nil)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	kaos := doc["kaos"].(map[string]any)
	if _, ok := kaos["jwks"]; ok {
		t.Fatalf("demo mode must not carry jwks: %v", kaos)
	}
	g := kaos["grants"].(map[string]any)["kaos://agent/demo/researcher"].([]any)
	if g[0] != "kaos://mcpserver/demo/github" {
		t.Fatalf("grants = %v", g)
	}
}

func TestDataDocumentVerifiedModeCarriesJWKS(t *testing.T) {
	jwks := map[string]any{"keys": []any{map[string]any{"kty": "RSA", "kid": "x"}}}
	raw, err := DataDocument(map[string][]string{}, jwks)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := doc["kaos"].(map[string]any)["jwks"]; !ok {
		t.Fatalf("verified mode must carry jwks: %v", doc)
	}
}

func TestConfigMapDataCarriesPolicyAndData(t *testing.T) {
	cm, err := ConfigMapData(map[string][]string{"a": {"b"}}, nil)
	if err != nil {
		t.Fatalf("ConfigMapData: %v", err)
	}
	if !strings.Contains(cm[PolicyKey], "package "+PolicyPackage) {
		t.Fatalf("policy key missing rego")
	}
	if !strings.Contains(cm[DataKey], "grants") {
		t.Fatalf("data key missing grants")
	}
}
