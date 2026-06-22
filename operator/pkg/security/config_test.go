package security

import (
	"testing"
)

func TestGetConfigDisabledByDefault(t *testing.T) {
	t.Setenv(envExtAuthzURL, "")

	cfg := GetConfig()

	if cfg.IsOperational() {
		t.Errorf("expected not operational when ext_authz URL is unset")
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
