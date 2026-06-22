package security

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func operationalConfig() Config {
	return Config{ExtAuthzURL: "aib-access-check.kaos-system.svc.cluster.local:9191"}
}

func TestConstructSecurityPolicyShape(t *testing.T) {
	params := PolicyParams{
		Name:      "mcp-github",
		Namespace: "default",
		RouteName: "mcp-github",
		Labels:    map[string]string{"app": "kaos"},
	}

	policy, err := constructSecurityPolicy(params, operationalConfig())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if gvk := policy.GroupVersionKind(); gvk != SecurityPolicyGVK {
		t.Fatalf("unexpected GVK %v", gvk)
	}
	if policy.GetName() != "mcp-github" || policy.GetNamespace() != "default" {
		t.Fatalf("unexpected name/namespace %s/%s", policy.GetName(), policy.GetNamespace())
	}
	if policy.GetLabels()["app"] != "kaos" {
		t.Errorf("expected app=kaos label")
	}

	targetRefs, found, err := unstructured.NestedSlice(policy.Object, "spec", "targetRefs")
	if err != nil || !found || len(targetRefs) != 1 {
		t.Fatalf("expected one targetRef, got found=%v err=%v len=%d", found, err, len(targetRefs))
	}
	ref := targetRefs[0].(map[string]interface{})
	if ref["group"] != "gateway.networking.k8s.io" || ref["kind"] != "HTTPRoute" || ref["name"] != "mcp-github" {
		t.Errorf("unexpected targetRef %#v", ref)
	}

	failOpen, found, err := unstructured.NestedBool(policy.Object, "spec", "extAuth", "failOpen")
	if err != nil || !found || failOpen {
		t.Errorf("expected failOpen=false, got %v (found=%v err=%v)", failOpen, found, err)
	}

	headers, found, err := unstructured.NestedStringSlice(policy.Object, "spec", "extAuth", "headersToExtAuth")
	if err != nil || !found {
		t.Fatalf("expected headersToExtAuth, found=%v err=%v", found, err)
	}
	if len(headers) != 2 || headers[0] != "authorization" || headers[1] != "x-agent-authorization" {
		t.Errorf("unexpected headersToExtAuth %#v", headers)
	}

	backendRef, found, err := unstructured.NestedMap(policy.Object, "spec", "extAuth", "grpc", "backendRef")
	if err != nil || !found {
		t.Fatalf("expected grpc backendRef, found=%v err=%v", found, err)
	}
	if backendRef["kind"] != "Service" || backendRef["name"] != "aib-access-check" ||
		backendRef["namespace"] != "kaos-system" {
		t.Errorf("unexpected backendRef %#v", backendRef)
	}
	if port, ok := backendRef["port"].(int64); !ok || port != 9191 {
		t.Errorf("expected port int64(9191), got %#v", backendRef["port"])
	}
}

func TestConstructSecurityPolicyNoLabels(t *testing.T) {
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, operationalConfig())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(policy.GetLabels()) != 0 {
		t.Errorf("expected no labels, got %v", policy.GetLabels())
	}
}

func TestConstructSecurityPolicyInvalidConfig(t *testing.T) {
	if _, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, Config{ExtAuthzURL: "no-port"}); err == nil {
		t.Errorf("expected error for malformed ext_authz URL")
	}
}

func bothIssuersConfig() Config {
	cfg := operationalConfig()
	cfg.Issuer = "http://aib-enduser.kaos-system.svc.cluster.local:8000"
	cfg.UserIssuer = "http://keycloak.kaos-system.svc.cluster.local:8080/realms/kaos"
	cfg.UserAudience = "kaos"
	return cfg
}

func jwtProviders(t *testing.T, policy *unstructured.Unstructured) []interface{} {
	t.Helper()
	providers, found, err := unstructured.NestedSlice(policy.Object, "spec", "jwt", "providers")
	if err != nil {
		t.Fatalf("error reading jwt providers: %v", err)
	}
	if !found {
		return nil
	}
	return providers
}

func providerByName(providers []interface{}, name string) map[string]interface{} {
	for _, p := range providers {
		m, ok := p.(map[string]interface{})
		if ok && m["name"] == name {
			return m
		}
	}
	return nil
}

func TestConstructSecurityPolicyEmitsBothJWTProviders(t *testing.T) {
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, bothIssuersConfig())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// extAuth must remain unchanged alongside the jwt block.
	failOpen, found, _ := unstructured.NestedBool(policy.Object, "spec", "extAuth", "failOpen")
	if !found || failOpen {
		t.Errorf("expected extAuth.failOpen=false to be preserved")
	}

	providers := jwtProviders(t, policy)
	if len(providers) != 2 {
		t.Fatalf("expected 2 jwt providers, got %d", len(providers))
	}

	agent := providerByName(providers, "agent")
	if agent == nil {
		t.Fatalf("expected an agent provider")
	}
	if agent["issuer"] != "http://aib-enduser.kaos-system.svc.cluster.local:8000" {
		t.Errorf("unexpected agent issuer %#v", agent["issuer"])
	}
	agentJWKS, _, _ := unstructured.NestedString(agent, "remoteJWKS", "uri")
	if agentJWKS != "http://aib-enduser.kaos-system.svc.cluster.local:8000/oauth2/jwks.json" {
		t.Errorf("unexpected agent jwks %q", agentJWKS)
	}
	agentHeaders, _, _ := unstructured.NestedSlice(agent, "extractFrom", "headers")
	if len(agentHeaders) != 1 {
		t.Fatalf("expected agent to extract from one header, got %d", len(agentHeaders))
	}
	h := agentHeaders[0].(map[string]interface{})
	if h["name"] != "x-agent-authorization" || h["valuePrefix"] != "Bearer " {
		t.Errorf("unexpected agent extractFrom header %#v", h)
	}
	if _, hasAud := agent["audiences"]; hasAud {
		t.Errorf("agent provider should not set audiences")
	}

	user := providerByName(providers, "user")
	if user == nil {
		t.Fatalf("expected a user provider")
	}
	if user["issuer"] != "http://keycloak.kaos-system.svc.cluster.local:8080/realms/kaos" {
		t.Errorf("unexpected user issuer %#v", user["issuer"])
	}
	userJWKS, _, _ := unstructured.NestedString(user, "remoteJWKS", "uri")
	if userJWKS != "http://keycloak.kaos-system.svc.cluster.local:8080/realms/kaos/protocol/openid-connect/certs" {
		t.Errorf("unexpected user jwks %q", userJWKS)
	}
	userAud, _, _ := unstructured.NestedStringSlice(user, "audiences")
	if len(userAud) != 1 || userAud[0] != "kaos" {
		t.Errorf("unexpected user audiences %#v", userAud)
	}
	if _, hasExtract := user["extractFrom"]; hasExtract {
		t.Errorf("user provider should use default Authorization extraction, got explicit extractFrom")
	}
	userClaims, _, _ := unstructured.NestedSlice(user, "claimToHeaders")
	if len(userClaims) != 2 {
		t.Errorf("expected two user claimToHeaders, got %d", len(userClaims))
	}
}

func TestConstructSecurityPolicyAgentOnlyWhenNoUserIssuer(t *testing.T) {
	cfg := operationalConfig()
	cfg.Issuer = "http://aib:8000"

	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	providers := jwtProviders(t, policy)
	if len(providers) != 1 {
		t.Fatalf("expected only the agent provider, got %d", len(providers))
	}
	if providerByName(providers, "agent") == nil {
		t.Errorf("expected the agent provider to be present")
	}
	if providerByName(providers, "user") != nil {
		t.Errorf("did not expect a user provider without a user issuer")
	}
}

func TestConstructSecurityPolicyNoJWTBlockWhenDisabled(t *testing.T) {
	// Operational (ext_authz) but no issuers configured: no jwt block at all.
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, operationalConfig())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, found, _ := unstructured.NestedMap(policy.Object, "spec", "jwt"); found {
		t.Errorf("expected no spec.jwt block when no issuers are configured")
	}
	// extAuth must still be present.
	if _, found, _ := unstructured.NestedMap(policy.Object, "spec", "extAuth"); !found {
		t.Errorf("expected extAuth to be present")
	}
}
