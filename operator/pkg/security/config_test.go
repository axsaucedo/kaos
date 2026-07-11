package security

import (
	"testing"
)

func TestGetConfigDisabledByDefault(t *testing.T) {
	t.Setenv(envExtAuthzURL, "")
	t.Setenv(envPDPEnabled, "")

	cfg := GetConfig()

	if cfg.IsOperational() {
		t.Errorf("expected not operational when ext_authz URL is unset")
	}
}

func TestGetConfigOperationalWhenPDPEnabled(t *testing.T) {
	t.Setenv(envPDPEnabled, "true")
	t.Setenv(envOperatorNamespace, "kaos-system")

	cfg := GetConfig()
	if !cfg.IsOperational() {
		t.Fatal("expected PDP to enable ext_authz enforcement")
	}
	if got := cfg.ExtAuthzURLOrDefault(); got != "kaos-pdp.kaos-system.svc:9191" {
		t.Fatalf("ExtAuthzURLOrDefault() = %q", got)
	}
	name, namespace, port, err := cfg.ExtAuthzBackendRef()
	if err != nil {
		t.Fatalf("ExtAuthzBackendRef(): %v", err)
	}
	if name != "kaos-pdp" || namespace != "kaos-system" || port != 9191 {
		t.Fatalf("backend = %s/%s:%d", namespace, name, port)
	}
}

func TestExtAuthzURLOverrideTakesPrecedenceOverPDPDefault(t *testing.T) {
	cfg := Config{
		PDPEnabled:        true,
		OperatorNamespace: "kaos-system",
		ExtAuthzURL:       "custom-authz.custom-system.svc:9002",
	}
	if got := cfg.ExtAuthzURLOrDefault(); got != cfg.ExtAuthzURL {
		t.Fatalf("ExtAuthzURLOrDefault() = %q, want override %q", got, cfg.ExtAuthzURL)
	}
	name, namespace, port, err := cfg.ExtAuthzBackendRef()
	if err != nil {
		t.Fatalf("ExtAuthzBackendRef(): %v", err)
	}
	if name != "custom-authz" || namespace != "custom-system" || port != 9002 {
		t.Fatalf("backend = %s/%s:%d", namespace, name, port)
	}
}

func TestGetConfigOperationalWhenURLSet(t *testing.T) {
	t.Setenv(envExtAuthzURL, "aib-ext-authz.aib-system.svc.cluster.local:9002")

	cfg := GetConfig()

	if !cfg.IsOperational() {
		t.Fatalf("expected operational when ext_authz URL is set")
	}

	name, namespace, port, err := cfg.ExtAuthzBackendRef()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if name != "aib-ext-authz" {
		t.Errorf("unexpected service name %q", name)
	}
	if namespace != "aib-system" {
		t.Errorf("unexpected namespace %q", namespace)
	}
	if port != 9002 {
		t.Errorf("unexpected port %d", port)
	}
}

func TestIsOperationalIgnoresWhitespace(t *testing.T) {
	if (Config{ExtAuthzURL: "   "}).IsOperational() {
		t.Errorf("expected whitespace-only URL to be non-operational")
	}
}

func TestCredentialMountingEnabled(t *testing.T) {
	cases := []struct {
		name     string
		extAuth  string
		prefix   string
		expected bool
	}{
		{"disabled when nothing set", "", "", false},
		{"disabled without ext_authz", "", "kaos-aib", false},
		{"disabled without prefix", "svc:9002", "", false},
		{"disabled with whitespace prefix", "svc:9002", "  ", false},
		{"enabled when both set", "svc:9002", "kaos-aib", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Config{ExtAuthzURL: tc.extAuth, CredentialSecretPrefix: tc.prefix}
			if cfg.CredentialMountingEnabled() != tc.expected {
				t.Errorf("CredentialMountingEnabled() = %v, want %v", !tc.expected, tc.expected)
			}
		})
	}
}

func TestCredentialSecretName(t *testing.T) {
	cfg := Config{CredentialSecretPrefix: "kaos-aib"}
	if got := cfg.CredentialSecretName("researcher"); got != "kaos-aib-researcher" {
		t.Errorf("CredentialSecretName = %q, want kaos-aib-researcher", got)
	}
}

func TestTokenEndpoint(t *testing.T) {
	cases := []struct {
		name   string
		issuer string
		want   string
	}{
		{"empty issuer", "", ""},
		{"issuer without slash", "http://aib:8000", "http://aib:8000/oauth2/token"},
		{"issuer with trailing slash", "http://aib:8000/", "http://aib:8000/oauth2/token"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := (Config{Issuer: tc.issuer}).TokenEndpoint(); got != tc.want {
				t.Errorf("TokenEndpoint() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestGetConfigReadsAllFields(t *testing.T) {
	t.Setenv(envExtAuthzURL, "aib-ext-authz.aib-system:9002")
	t.Setenv(envIssuer, "http://aib-enduser.aib-system.svc.cluster.local:8000")
	t.Setenv(envCredentialSecretPrefix, "kaos-aib")
	t.Setenv(envUserIssuer, "http://keycloak.kaos-system.svc.cluster.local:8080/realms/kaos")
	t.Setenv(envUserAudience, "kaos")
	t.Setenv(envUserJWKSURI, "")

	cfg := GetConfig()

	if !cfg.CredentialMountingEnabled() {
		t.Errorf("expected credential mounting enabled")
	}
	if cfg.TokenEndpoint() != "http://aib-enduser.aib-system.svc.cluster.local:8000/oauth2/token" {
		t.Errorf("unexpected token endpoint %q", cfg.TokenEndpoint())
	}
	if cfg.UserIssuer != "http://keycloak.kaos-system.svc.cluster.local:8080/realms/kaos" {
		t.Errorf("unexpected user issuer %q", cfg.UserIssuer)
	}
	if cfg.UserAudience != "kaos" {
		t.Errorf("unexpected user audience %q", cfg.UserAudience)
	}
}

func TestIdentityProviderSelection(t *testing.T) {
	cases := []struct {
		configured string
		want       IdentityProvider
	}{
		{"", IdentityProviderAIB},
		{"aib", IdentityProviderAIB},
		{"oidc", IdentityProviderOIDC},
		{"serviceaccount", IdentityProviderServiceAccount},
		{"invalid", IdentityProviderAIB},
	}
	for _, tc := range cases {
		t.Run(tc.configured, func(t *testing.T) {
			cfg := Config{IdentityProvider: IdentityProvider(tc.configured)}
			if got := cfg.IdentityProviderOrDefault(); got != tc.want {
				t.Fatalf("IdentityProviderOrDefault() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestServiceAccountIdentityDefaults(t *testing.T) {
	t.Setenv(envIdentityProvider, "serviceaccount")
	t.Setenv(envServiceAccountAudience, "")
	t.Setenv(envServiceAccountExpiration, "")
	t.Setenv(envServiceAccountTokenPath, "")
	cfg := GetConfig()
	if !cfg.ServiceAccountIdentityEnabled() {
		t.Fatal("expected ServiceAccount identity")
	}
	if cfg.ServiceAccountAudience != "kaos-gateway" || cfg.ServiceAccountTokenExpirationSeconds != 3600 {
		t.Fatalf("unexpected token projection defaults: %+v", cfg)
	}
	if cfg.ServiceAccountTokenPath != "/var/run/secrets/kaos-agent/token" {
		t.Fatalf("token path = %q", cfg.ServiceAccountTokenPath)
	}
}

func TestServiceAccountModeDisablesAIBCredentialMounting(t *testing.T) {
	cfg := Config{
		IdentityProvider:       IdentityProviderServiceAccount,
		PDPEnabled:             true,
		CredentialSecretPrefix: "kaos-aib",
	}
	if cfg.CredentialMountingEnabled() {
		t.Fatal("ServiceAccount identity must not mount AIB credentials")
	}
}

func TestJWTEnabled(t *testing.T) {
	cases := []struct {
		name       string
		issuer     string
		userIssuer string
		want       bool
	}{
		{"neither", "", "", false},
		{"agent only", "http://aib:8000", "", true},
		{"user only", "", "http://kc/realms/kaos", true},
		{"both", "http://aib:8000", "http://kc/realms/kaos", true},
		{"whitespace only", "  ", "  ", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Config{Issuer: tc.issuer, UserIssuer: tc.userIssuer}
			if cfg.JWTEnabled() != tc.want {
				t.Errorf("JWTEnabled() = %v, want %v", cfg.JWTEnabled(), tc.want)
			}
		})
	}
}

func TestAgentJWKSURI(t *testing.T) {
	cases := []struct {
		name   string
		issuer string
		want   string
	}{
		{"empty issuer", "", ""},
		{"issuer without slash", "http://aib:8000", "http://aib:8000/oauth2/jwks.json"},
		{"issuer with trailing slash", "http://aib:8000/", "http://aib:8000/oauth2/jwks.json"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := (Config{Issuer: tc.issuer}).AgentJWKSURI(); got != tc.want {
				t.Errorf("AgentJWKSURI() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestAuthzJWKSURI(t *testing.T) {
	cases := []struct {
		name             string
		issuer           string
		verificationMode AgentJWTVerificationMode
		want             string
	}{
		{"skip default without issuer", "", "", ""},
		{"verified default with issuer", "http://aib:8000", "", "http://aib:8000/oauth2/jwks.json"},
		{"forced skip suppresses jwks", "http://aib:8000", VerificationSkip, ""},
		{"forced verified without issuer", "", VerificationVerified, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := Config{Issuer: tc.issuer, AgentJWTVerificationMode: tc.verificationMode}
			if got := c.AuthzJWKSURI(); got != tc.want {
				t.Errorf("AuthzJWKSURI() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestUserJWKSURI(t *testing.T) {
	cases := []struct {
		name       string
		userIssuer string
		override   string
		want       string
	}{
		{"empty", "", "", ""},
		{"derived from realm issuer", "http://kc/realms/kaos", "", "http://kc/realms/kaos/protocol/openid-connect/certs"},
		{"derived trims trailing slash", "http://kc/realms/kaos/", "", "http://kc/realms/kaos/protocol/openid-connect/certs"},
		{"explicit override wins", "http://kc/realms/kaos", "http://kc/custom/jwks", "http://kc/custom/jwks"},
		{"override without issuer", "", "http://kc/custom/jwks", "http://kc/custom/jwks"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Config{UserIssuer: tc.userIssuer, UserJWKSURIOverride: tc.override}
			if got := cfg.UserJWKSURI(); got != tc.want {
				t.Errorf("UserJWKSURI() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestExtAuthzBackendRef(t *testing.T) {
	cases := []struct {
		name      string
		url       string
		wantName  string
		wantNS    string
		wantPort  int
		wantError bool
	}{
		{"fqdn", "svc.ns.svc.cluster.local:9191", "svc", "ns", 9191, false},
		{"name and namespace", "svc.ns:9002", "svc", "ns", 9002, false},
		{"name only", "svc:8080", "svc", "", 8080, false},
		{"missing port", "svc.ns", "", "", 0, true},
		{"empty", "", "", "", 0, true},
		{"invalid port", "svc.ns:nope", "", "", 0, true},
		{"zero port", "svc.ns:0", "", "", 0, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			name, ns, port, err := (Config{ExtAuthzURL: tc.url}).ExtAuthzBackendRef()
			if tc.wantError {
				if err == nil {
					t.Fatalf("expected error for %q", tc.url)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if name != tc.wantName || ns != tc.wantNS || port != tc.wantPort {
				t.Errorf("got (%q,%q,%d), want (%q,%q,%d)", name, ns, port, tc.wantName, tc.wantNS, tc.wantPort)
			}
		})
	}
}

func TestNetworkPolicyEnabled(t *testing.T) {
	cases := []struct {
		name       string
		extAuthz   string
		npDisabled bool
		strict     bool
		want       bool
	}{
		{"operational and not disabled", "svc:9191", false, false, true},
		{"operational but disabled", "svc:9191", true, false, false},
		{"not operational", "", false, false, false},
		{"not operational and disabled", "", true, false, false},
		{"strict standalone without any hook", "", false, true, true},
		{"strict overrides the escape hatch", "", true, true, true},
		{"strict with operational", "svc:9191", false, true, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Config{ExtAuthzURL: tc.extAuthz, NetworkPolicyDisabled: tc.npDisabled, StrictGatewayAPI: tc.strict}
			if got := cfg.NetworkPolicyEnabled(); got != tc.want {
				t.Errorf("NetworkPolicyEnabled() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestGatewayRoutingEnabledWithStrict(t *testing.T) {
	if !(Config{StrictGatewayAPI: true}).GatewayRoutingEnabled() {
		t.Errorf("expected strict gateway API to enable gateway routing")
	}
	if !(Config{StrictGatewayAPI: true}).NetworkPolicyEnabled() {
		t.Errorf("expected strict gateway API to enable NetworkPolicy standalone")
	}
	if (Config{}).GatewayRoutingEnabled() {
		t.Errorf("expected gateway routing off with no flags")
	}
}

func TestGetConfigReadsStrictGatewayAPI(t *testing.T) {
	t.Setenv("SECURITY_STRICT_GATEWAY_API_ENABLED", "true")
	cfg := GetConfig()
	if !cfg.StrictGatewayAPI {
		t.Errorf("expected StrictGatewayAPI true")
	}
	if !cfg.NetworkPolicyEnabled() || !cfg.GatewayRoutingEnabled() {
		t.Errorf("expected strict gateway API to enable NetworkPolicy and gateway routing standalone")
	}
}

func TestNetworkPolicyEgressEnabled(t *testing.T) {
	cases := []struct {
		name     string
		cfg      Config
		expected bool
	}{
		{"default off", Config{ExtAuthzURL: "svc:9191"}, false},
		{"enabled with base policy", Config{ExtAuthzURL: "svc:9191", NetworkPolicyEgress: true}, true},
		{"disabled when base policy disabled", Config{ExtAuthzURL: "svc:9191", NetworkPolicyDisabled: true, NetworkPolicyEgress: true}, false},
		{"disabled when not operational", Config{NetworkPolicyEgress: true}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.cfg.NetworkPolicyEgressEnabled(); got != tc.expected {
				t.Errorf("NetworkPolicyEgressEnabled() = %v, want %v", got, tc.expected)
			}
		})
	}
}

func TestGatewayNamespaceOrDefault(t *testing.T) {
	if got := (Config{}).GatewayNamespaceOrDefault(); got != defaultGatewayNamespace {
		t.Errorf("default = %q, want %q", got, defaultGatewayNamespace)
	}
	if got := (Config{GatewayNamespace: "eg"}).GatewayNamespaceOrDefault(); got != "eg" {
		t.Errorf("explicit = %q, want eg", got)
	}
	if got := (Config{GatewayNamespace: "  "}).GatewayNamespaceOrDefault(); got != defaultGatewayNamespace {
		t.Errorf("whitespace = %q, want default", got)
	}
}

func TestOperatorNamespaceOrDefault(t *testing.T) {
	if got := (Config{}).OperatorNamespaceOrDefault(); got != defaultOperatorNamespace {
		t.Errorf("default = %q, want %q", got, defaultOperatorNamespace)
	}
	if got := (Config{OperatorNamespace: "ops"}).OperatorNamespaceOrDefault(); got != "ops" {
		t.Errorf("explicit = %q, want ops", got)
	}
}

func TestGetConfigOperatorNamespaceFallsBackToPodNamespace(t *testing.T) {
	t.Setenv(envExtAuthzURL, "svc:9191")
	t.Setenv(envOperatorNamespace, "")
	t.Setenv(envPodNamespace, "kaos-system")
	if got := GetConfig().OperatorNamespace; got != "kaos-system" {
		t.Errorf("OperatorNamespace = %q, want kaos-system (from POD_NAMESPACE)", got)
	}

	t.Setenv(envOperatorNamespace, "explicit-ns")
	if got := GetConfig().OperatorNamespace; got != "explicit-ns" {
		t.Errorf("OperatorNamespace = %q, want explicit-ns (SECURITY_OPERATOR_NAMESPACE wins)", got)
	}
}

func TestGetConfigNetworkPolicyDisabledParsing(t *testing.T) {
	t.Setenv(envExtAuthzURL, "svc:9191")
	t.Setenv(envNetworkPolicyDisabled, "true")
	if !GetConfig().NetworkPolicyDisabled {
		t.Errorf("expected NetworkPolicyDisabled=true")
	}
	t.Setenv(envNetworkPolicyDisabled, "")
	if GetConfig().NetworkPolicyDisabled {
		t.Errorf("expected NetworkPolicyDisabled=false when unset")
	}
}

func TestGetConfigNetworkPolicyEgressParsing(t *testing.T) {
	t.Setenv(envExtAuthzURL, "svc:9191")
	t.Setenv(envNetworkPolicyEgress, "true")
	cfg := GetConfig()
	if !cfg.NetworkPolicyEgress {
		t.Errorf("expected NetworkPolicyEgress=true")
	}
	if !cfg.NetworkPolicyEgressEnabled() {
		t.Errorf("expected NetworkPolicyEgressEnabled=true when base NetworkPolicy is on")
	}

	t.Setenv(envNetworkPolicyDisabled, "true")
	if GetConfig().NetworkPolicyEgressEnabled() {
		t.Errorf("expected egress disabled when base NetworkPolicy is disabled")
	}
}

func TestGatewayRoutingEnabled(t *testing.T) {
	if (Config{}).GatewayRoutingEnabled() {
		t.Errorf("expected routing disabled by default")
	}
	if !(Config{GatewayRouting: true}).GatewayRoutingEnabled() {
		t.Errorf("expected routing enabled when flag set")
	}
}

func TestGetConfigReadsGatewayRoutingFields(t *testing.T) {
	t.Setenv(envExtAuthzURL, "svc:9191")
	t.Setenv(envGatewayHost, "172.18.0.4:80")
	t.Setenv(envGatewayRouting, "true")
	cfg := GetConfig()
	if cfg.GatewayHost != "172.18.0.4:80" {
		t.Errorf("GatewayHost = %q, want 172.18.0.4:80", cfg.GatewayHost)
	}
	if !cfg.GatewayRoutingEnabled() {
		t.Errorf("expected GatewayRoutingEnabled true")
	}
}

func TestSecurityEnabled(t *testing.T) {
	cases := []struct {
		name     string
		extAuthz string
		pdp      bool
		want     bool
	}{
		{"nothing set", "", false, false},
		{"ext_authz set", "svc:9002", false, true},
		{"PDP enabled", "", true, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Config{ExtAuthzURL: tc.extAuthz, PDPEnabled: tc.pdp}
			if got := cfg.SecurityEnabled(); got != tc.want {
				t.Errorf("SecurityEnabled() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestExtAuthzEnabled(t *testing.T) {
	url := "aib-access-check.kaos-system.svc.cluster.local:9191"
	cases := []struct {
		name string
		cfg  Config
		want bool
	}{
		{"url on", Config{ExtAuthzURL: url}, true},
		{"PDP on", Config{PDPEnabled: true}, true},
		{"without url off", Config{}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.cfg.ExtAuthzEnabled(); got != tc.want {
				t.Errorf("ExtAuthzEnabled() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestAgentJWTVerificationModeOrDefault(t *testing.T) {
	cases := []struct {
		name   string
		mode   AgentJWTVerificationMode
		issuer string
		want   AgentJWTVerificationMode
	}{
		{"derive skip without issuer", "", "", VerificationSkip},
		{"derive verified with issuer", "", "http://aib:8000", VerificationVerified},
		{"explicit skip overrides issuer", "skip", "http://aib:8000", VerificationSkip},
		{"explicit verified without issuer", "verified", "", VerificationVerified},
		{"bogus falls back to derived", "bogus", "http://aib:8000", VerificationVerified},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Config{AgentJWTVerificationMode: tc.mode, Issuer: tc.issuer}
			if got := cfg.AgentJWTVerificationModeOrDefault(); got != tc.want {
				t.Errorf("AgentJWTVerificationModeOrDefault() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestPolicyDataSourceOrDefault(t *testing.T) {
	cases := []struct {
		in   PolicyDataSource
		want PolicyDataSource
	}{
		{"", PolicyDataAutomated},
		{"automated", PolicyDataAutomated},
		{"manual", PolicyDataManual},
		{"external", PolicyDataAutomated},
		{"bogus", PolicyDataAutomated},
	}
	for _, tc := range cases {
		if got := (Config{PolicyDataSource: tc.in}).PolicyDataSourceOrDefault(); got != tc.want {
			t.Errorf("PolicyDataSourceOrDefault(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestGetConfigReadsAuthorizationModes(t *testing.T) {
	t.Setenv(envAgentJWTVerification, "Verified")
	t.Setenv(envPolicyDataSource, "External")
	t.Setenv(envPolicyRegoOverride, "true")

	cfg := GetConfig()

	if got := cfg.AgentJWTVerificationModeOrDefault(); got != VerificationVerified {
		t.Errorf("AgentJWTVerificationMode = %q, want verified", got)
	}
	if got := cfg.PolicyDataSourceOrDefault(); got != PolicyDataAutomated {
		t.Errorf("PolicyDataSource = %q, want automated", got)
	}
	if !cfg.PolicyRegoOverride {
		t.Errorf("PolicyRegoOverride = false, want true")
	}
}
