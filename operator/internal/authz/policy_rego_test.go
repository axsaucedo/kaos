package authz

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

// TestPolicyRegoUnitTests runs the OPA rego unit tests for the enforcement policy
// against a real OPA evaluation. It uses the opa binary from the OPA environment
// variable or PATH and skips when neither is available, so it validates locally
// and in any CI job that provides opa without failing environments that do not.
func TestPolicyRegoUnitTests(t *testing.T) {
	opa := os.Getenv("OPA")
	if opa == "" {
		found, err := exec.LookPath("opa")
		if err != nil {
			t.Skip("opa binary not found (set OPA or add opa to PATH to run policy tests)")
		}
		opa = found
	}

	policy, err := filepath.Abs("policy.rego")
	if err != nil {
		t.Fatalf("resolving policy path: %v", err)
	}
	tests, err := filepath.Abs("policy_parity_test.rego")
	if err != nil {
		t.Fatalf("resolving policy test path: %v", err)
	}

	out, err := exec.Command(opa, "test", policy, tests).CombinedOutput()
	if err != nil {
		t.Fatalf("opa test failed: %v\n%s", err, out)
	}
}
