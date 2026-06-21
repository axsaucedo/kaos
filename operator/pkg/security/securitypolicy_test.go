package security

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func operationalConfig() Config {
	return Config{
		Enabled:                  true,
		ExtAuthzServiceName:      "aib-access-check",
		ExtAuthzServiceNamespace: "kaos-system",
		ExtAuthzServicePort:      9191,
		DefaultAction:            "access",
	}
}

func TestConstructSecurityPolicyShape(t *testing.T) {
	params := PolicyParams{
		Name:      "mcp-github",
		Namespace: "default",
		RouteName: "mcp-github",
		Labels:    map[string]string{"app": "kaos"},
	}

	policy := constructSecurityPolicy(params, operationalConfig())

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
	policy := constructSecurityPolicy(PolicyParams{Name: "a", Namespace: "ns", RouteName: "a"}, operationalConfig())
	if len(policy.GetLabels()) != 0 {
		t.Errorf("expected no labels, got %v", policy.GetLabels())
	}
}
