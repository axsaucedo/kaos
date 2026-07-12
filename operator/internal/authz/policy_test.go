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

func TestDataDocumentWithoutJWKSOmitsJWKS(t *testing.T) {
	grants := map[string][]string{"kaos://agent/demo/researcher": {"kaos://mcpserver/demo/github"}}
	raw, err := DataDocument(grants, nil, "", nil, nil)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	kaos := doc["kaos"].(map[string]any)
	if _, ok := kaos["jwks"]; ok {
		t.Fatalf("data without verification keys must not carry jwks: %v", kaos)
	}
	g := kaos["grants"].(map[string]any)["kaos://agent/demo/researcher"].([]any)
	if g[0] != "kaos://mcpserver/demo/github" {
		t.Fatalf("grants = %v", g)
	}
}

func TestDataDocumentVerifiedModeCarriesJWKS(t *testing.T) {
	jwks := map[string]any{"keys": []any{map[string]any{"kty": "RSA", "kid": "x"}}}
	raw, err := DataDocument(map[string][]string{}, nil, "https://issuer.example", jwks, nil)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	issuerJWKS := doc["kaos"].(map[string]any)["jwks"].(map[string]any)
	if _, ok := issuerJWKS["https://issuer.example"]; !ok {
		t.Fatalf("verified mode must carry jwks: %v", doc)
	}
}

func TestDataDocumentCarriesAgentIssuerSubjectMapping(t *testing.T) {
	agents := map[string]map[string]any{
		"kaos://agent/demo/researcher": {
			"issuer_sub": "system:serviceaccount:demo:kaos-agent-researcher",
			"autonomous": true,
		},
	}
	raw, err := DataDocument(map[string][]string{}, nil, "", nil, agents)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	got := doc["kaos"].(map[string]any)["agents"].(map[string]any)["kaos://agent/demo/researcher"].(map[string]any)
	if got["issuer_sub"] != "system:serviceaccount:demo:kaos-agent-researcher" {
		t.Fatalf("issuer_sub = %v", got["issuer_sub"])
	}
	if autonomous, ok := got["autonomous"].(bool); !ok || !autonomous {
		t.Fatalf("autonomous = %v (%T), want true bool", got["autonomous"], got["autonomous"])
	}
}

func TestConfigMapDataCarriesPolicyAndData(t *testing.T) {
	cm, err := ConfigMapData(map[string][]string{"a": {"b"}}, nil, "", nil, nil)
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

func TestDataDocumentCarriesUserGrantsWhenPresent(t *testing.T) {
	raw, err := DataDocument(nil, map[string][]string{"user:alice": {"kaos://agent/demo/a"}}, "", nil, nil)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	if !strings.Contains(string(raw), `"user_grants"`) || !strings.Contains(string(raw), `"user:alice"`) {
		t.Fatalf("data missing user_grants: %s", raw)
	}
}

func TestDataDocumentOmitsEmptyUserGrants(t *testing.T) {
	raw, err := DataDocument(nil, map[string][]string{}, "", nil, nil)
	if err != nil {
		t.Fatalf("DataDocument: %v", err)
	}
	if strings.Contains(string(raw), `"user_grants"`) {
		t.Fatalf("data must omit empty user_grants: %s", raw)
	}
}
