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

	cfg := GetConfig()

	if !cfg.CredentialMountingEnabled() {
		t.Errorf("expected credential mounting enabled")
	}
	if cfg.TokenEndpoint() != "http://aib-enduser.aib-system.svc.cluster.local:8000/oauth2/token" {
		t.Errorf("unexpected token endpoint %q", cfg.TokenEndpoint())
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
