package security

import (
	"testing"
)

func TestGetConfigDefaults(t *testing.T) {
	for _, k := range []string{envEnabled, envExtAuthzName, envExtAuthzNamespace, envExtAuthzPort, envDefaultAction} {
		t.Setenv(k, "")
	}

	cfg := GetConfig()

	if cfg.Enabled {
		t.Errorf("expected Enabled false by default, got true")
	}
	if cfg.ExtAuthzServicePort != defaultExtAuthzPort {
		t.Errorf("expected default port %d, got %d", defaultExtAuthzPort, cfg.ExtAuthzServicePort)
	}
	if cfg.DefaultAction != defaultDefaultAction {
		t.Errorf("expected default action %q, got %q", defaultDefaultAction, cfg.DefaultAction)
	}
	if cfg.IsOperational() {
		t.Errorf("expected not operational when disabled and unset")
	}
}

func TestGetConfigEnabled(t *testing.T) {
	t.Setenv(envEnabled, "true")
	t.Setenv(envExtAuthzName, "aib-access-check")
	t.Setenv(envExtAuthzNamespace, "kaos-system")
	t.Setenv(envExtAuthzPort, "9191")
	t.Setenv(envDefaultAction, "call")

	cfg := GetConfig()

	if !cfg.Enabled {
		t.Errorf("expected Enabled true")
	}
	if cfg.ExtAuthzServiceName != "aib-access-check" {
		t.Errorf("unexpected service name %q", cfg.ExtAuthzServiceName)
	}
	if cfg.ExtAuthzServiceNamespace != "kaos-system" {
		t.Errorf("unexpected namespace %q", cfg.ExtAuthzServiceNamespace)
	}
	if cfg.ExtAuthzServicePort != 9191 {
		t.Errorf("unexpected port %d", cfg.ExtAuthzServicePort)
	}
	if cfg.DefaultAction != "call" {
		t.Errorf("unexpected action %q", cfg.DefaultAction)
	}
	if !cfg.IsOperational() {
		t.Errorf("expected operational when enabled and fully specified")
	}
	if got, want := cfg.ExtAuthzServiceHost(), "aib-access-check.kaos-system.svc.cluster.local"; got != want {
		t.Errorf("ExtAuthzServiceHost = %q, want %q", got, want)
	}
}

func TestIsOperationalRequiresAllFields(t *testing.T) {
	cases := []struct {
		name string
		cfg  Config
		want bool
	}{
		{"enabled but no name", Config{Enabled: true, ExtAuthzServiceNamespace: "ns", ExtAuthzServicePort: 9191}, false},
		{"enabled but no namespace", Config{Enabled: true, ExtAuthzServiceName: "svc", ExtAuthzServicePort: 9191}, false},
		{"enabled but no port", Config{Enabled: true, ExtAuthzServiceName: "svc", ExtAuthzServiceNamespace: "ns"}, false},
		{"disabled but fully specified", Config{ExtAuthzServiceName: "svc", ExtAuthzServiceNamespace: "ns", ExtAuthzServicePort: 9191}, false},
		{"fully specified and enabled", Config{Enabled: true, ExtAuthzServiceName: "svc", ExtAuthzServiceNamespace: "ns", ExtAuthzServicePort: 9191}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.cfg.IsOperational(); got != tc.want {
				t.Errorf("IsOperational() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestGetConfigInvalidPortFallsBack(t *testing.T) {
	t.Setenv(envExtAuthzPort, "not-a-number")
	if got := GetConfig().ExtAuthzServicePort; got != defaultExtAuthzPort {
		t.Errorf("expected fallback to %d on invalid port, got %d", defaultExtAuthzPort, got)
	}
}
