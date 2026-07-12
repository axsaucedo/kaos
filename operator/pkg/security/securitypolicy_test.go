package security

import (
	"strings"
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func operationalConfig() Config {
	return Config{
		ExtAuthzURL: "aib-access-check.kaos-system.svc.cluster.local:9191",
	}
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

func TestConstructExtAuthReferenceGrant(t *testing.T) {
	grant := constructExtAuthReferenceGrant("agents", "kaos-system", "kaos-pdp")
	if grant.GetNamespace() != "kaos-system" || !strings.HasPrefix(grant.GetName(), "kaos-ext-auth-") {
		t.Fatalf("unexpected ReferenceGrant identity %s/%s", grant.GetNamespace(), grant.GetName())
	}
	from, found, err := unstructured.NestedSlice(grant.Object, "spec", "from")
	if err != nil || !found || len(from) != 1 {
		t.Fatalf("from = %#v found=%v err=%v", from, found, err)
	}
	wantFrom := map[string]interface{}{
		"group": securityPolicyGroup, "kind": securityPolicyKind, "namespace": "agents",
	}
	if got := from[0].(map[string]interface{}); got["group"] != wantFrom["group"] || got["kind"] != wantFrom["kind"] || got["namespace"] != wantFrom["namespace"] {
		t.Fatalf("from = %#v", got)
	}
	to, found, err := unstructured.NestedSlice(grant.Object, "spec", "to")
	if err != nil || !found || len(to) != 1 {
		t.Fatalf("to = %#v found=%v err=%v", to, found, err)
	}
	gotTo := to[0].(map[string]interface{})
	if gotTo["group"] != "" || gotTo["kind"] != "Service" || gotTo["name"] != "kaos-pdp" {
		t.Fatalf("to = %#v", gotTo)
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
	cfg := Config{ExtAuthzURL: "no-port"}
	if _, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, cfg); err == nil {
		t.Errorf("expected error for malformed ext_authz URL")
	}
}

func TestConstructSecurityPolicyUsesPDPDefaultWhenEnabled(t *testing.T) {
	cfg := Config{PDPEnabled: true, OperatorNamespace: "kaos-system"}
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if policy == nil {
		t.Fatal("expected SecurityPolicy when PDP is enabled")
	}
	backendRef, found, err := unstructured.NestedMap(policy.Object, "spec", "extAuth", "grpc", "backendRef")
	if err != nil || !found {
		t.Fatalf("expected PDP backendRef, found=%v err=%v", found, err)
	}
	if backendRef["name"] != "kaos-pdp" || backendRef["namespace"] != "kaos-system" || backendRef["port"] != int64(9191) {
		t.Fatalf("unexpected PDP backendRef: %#v", backendRef)
	}
	failOpen, found, err := unstructured.NestedBool(policy.Object, "spec", "extAuth", "failOpen")
	if err != nil || !found || failOpen {
		t.Fatalf("expected explicit failOpen=false, got %v (found=%v err=%v)", failOpen, found, err)
	}
}

func TestConstructSecurityPolicyAbsentWhenPDPDisabled(t *testing.T) {
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, Config{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if policy != nil {
		t.Fatalf("expected no SecurityPolicy when PDP and JWT are disabled: %#v", policy.Object)
	}
}

func TestConstructSecurityPolicyJWTOnlyWithoutExtAuthz(t *testing.T) {
	cfg := Config{
		UserIssuer: "http://keycloak.kaos-system.svc.cluster.local:8080/realms/kaos",
	}
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if policy == nil {
		t.Fatal("expected a policy with jwt providers")
	}
	if _, found, _ := unstructured.NestedMap(policy.Object, "spec", "extAuth"); found {
		t.Errorf("expected no extAuth block without an ext_authz backend")
	}
	if _, found, _ := unstructured.NestedSlice(policy.Object, "spec", "jwt", "providers"); !found {
		t.Errorf("expected jwt providers to be attached")
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

func TestConstructSecurityPolicyServiceAccountUsesLocalJWKS(t *testing.T) {
	cfg := Config{
		PDPEnabled:             true,
		IdentityProvider:       IdentityProviderServiceAccount,
		ServiceAccountAudience: "kaos-gateway",
		ServiceAccountIssuer:   "https://kubernetes.default.svc",
		ServiceAccountJWKS: map[string]any{
			"keys": []any{map[string]any{"kty": "RSA", "kid": "sa-key"}},
		},
	}
	policy, err := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, cfg)
	if err != nil {
		t.Fatalf("constructSecurityPolicy: %v", err)
	}
	agent := providerByName(jwtProviders(t, policy), "agent")
	if agent == nil || agent["issuer"] != "https://kubernetes.default.svc" {
		t.Fatalf("agent provider = %#v", agent)
	}
	local, found, err := unstructured.NestedMap(agent, "localJWKS")
	if err != nil || !found || local["type"] != "Inline" {
		t.Fatalf("localJWKS = %#v found=%v err=%v", local, found, err)
	}
	inline, _ := local["inline"].(string)
	if !strings.Contains(inline, `"kid":"sa-key"`) {
		t.Fatalf("inline JWKS = %q", inline)
	}
	if _, remote := agent["remoteJWKS"]; remote {
		t.Fatal("ServiceAccount provider must not use remoteJWKS")
	}
	audiences, found, err := unstructured.NestedSlice(agent, "audiences")
	if err != nil || !found || len(audiences) != 1 || audiences[0] != "kaos-gateway" {
		t.Fatalf("audiences = %#v found=%v err=%v", audiences, found, err)
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

// TestConstructSecurityPolicyBackendRefIsConfigDriven proves the ext_authz
// backend is backend-neutral: swapping the default AIB access-check for an
// alternative gRPC ext_authz backend (e.g. opa-envoy) is a pure configuration
// change via ExtAuthzURL, with no change to the operator's policy generation.
func TestConstructSecurityPolicyBackendRefIsConfigDriven(t *testing.T) {
	params := PolicyParams{Name: "mcp-github", Namespace: "default", RouteName: "mcp-github"}

	cases := []struct {
		name     string
		url      string
		wantName string
		wantNS   string
		wantPort int64
	}{
		{
			name:     "default aib backend",
			url:      "aib-access-check.kaos-system.svc.cluster.local:9191",
			wantName: "aib-access-check",
			wantNS:   "kaos-system",
			wantPort: 9191,
		},
		{
			name:     "opa-envoy drop-in backend",
			url:      "opa-envoy.opa-system.svc.cluster.local:9191",
			wantName: "opa-envoy",
			wantNS:   "opa-system",
			wantPort: 9191,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			policy, err := constructSecurityPolicy(params, Config{ExtAuthzURL: tc.url})
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			backendRef, found, err := unstructured.NestedMap(policy.Object, "spec", "extAuth", "grpc", "backendRef")
			if err != nil || !found {
				t.Fatalf("expected grpc backendRef, found=%v err=%v", found, err)
			}
			if backendRef["kind"] != "Service" || backendRef["name"] != tc.wantName || backendRef["namespace"] != tc.wantNS {
				t.Errorf("backendRef did not follow ExtAuthzURL config: %#v", backendRef)
			}
			if port, ok := backendRef["port"].(int64); !ok || port != tc.wantPort {
				t.Errorf("expected port int64(%d), got %#v", tc.wantPort, backendRef["port"])
			}
		})
	}
}
