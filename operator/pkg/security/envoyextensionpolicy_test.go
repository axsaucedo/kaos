package security

import (
	"context"
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func extProcConfig() Config {
	return Config{ExtProcURL: "aib-extproc.kaos-system.svc.cluster.local:50051"}
}

func TestConstructEnvoyExtensionPolicyShape(t *testing.T) {
	params := PolicyParams{
		Name:      "mcp-github",
		Namespace: "default",
		RouteName: "mcp-github",
		Labels:    map[string]string{"app": "kaos"},
	}

	policy, err := constructEnvoyExtensionPolicy(params, extProcConfig())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if gvk := policy.GroupVersionKind(); gvk != EnvoyExtensionPolicyGVK {
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

	extProc, found, err := unstructured.NestedSlice(policy.Object, "spec", "extProc")
	if err != nil || !found || len(extProc) != 1 {
		t.Fatalf("expected one extProc entry, found=%v err=%v len=%d", found, err, len(extProc))
	}
	entry := extProc[0].(map[string]interface{})

	backendRefs, ok := entry["backendRefs"].([]interface{})
	if !ok || len(backendRefs) != 1 {
		t.Fatalf("expected one backendRef, got %#v", entry["backendRefs"])
	}
	backendRef := backendRefs[0].(map[string]interface{})
	if backendRef["name"] != "aib-extproc" || backendRef["namespace"] != "kaos-system" {
		t.Errorf("unexpected backendRef name/namespace %#v", backendRef)
	}
	if backendRef["kind"] != "Service" || backendRef["port"] != int64(50051) {
		t.Errorf("unexpected backendRef kind/port %#v", backendRef)
	}

	mode, ok := entry["processingMode"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected processingMode, got %#v", entry["processingMode"])
	}
	if _, ok := mode["request"]; !ok {
		t.Errorf("expected processingMode.request to be present, got %#v", mode)
	}
}

func TestConstructEnvoyExtensionPolicyBackendRefError(t *testing.T) {
	params := PolicyParams{Name: "x", Namespace: "default", RouteName: "x"}
	if _, err := constructEnvoyExtensionPolicy(params, Config{ExtProcURL: "no-port"}); err == nil {
		t.Fatalf("expected error for malformed ext_proc URL")
	}
}

func TestReconcileEnvoyExtensionPolicyNoopWhenDisabled(t *testing.T) {
	scheme := runtime.NewScheme()
	c := fake.NewClientBuilder().WithScheme(scheme).Build()
	owner := &unstructured.Unstructured{}
	owner.SetGroupVersionKind(SecurityPolicyGVK)
	owner.SetName("owner")
	owner.SetNamespace("default")

	params := PolicyParams{Name: "mcp-github", Namespace: "default", RouteName: "mcp-github"}

	// ExtProc disabled (empty URL): reconcile must be a no-op (early return before
	// any client interaction) and never construct or create a policy.
	if err := ReconcileEnvoyExtensionPolicy(context.Background(), c, scheme, owner, params, Config{}, ctrl.Log); err != nil {
		t.Fatalf("expected no-op reconcile to succeed, got error: %v", err)
	}
}
