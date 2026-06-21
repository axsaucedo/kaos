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
