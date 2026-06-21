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
