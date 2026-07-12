package controllers

import (
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestExtProcPolicyTargetsOnlyDeclaredThirdPartyRoute(t *testing.T) {
	service := &kaosv1alpha1.ThirdPartyService{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github"},
		Spec:       kaosv1alpha1.ThirdPartyServiceSpec{RouteRef: kaosv1alpha1.ThirdPartyServiceRouteRef{Name: "github-egress"}},
	}
	route := &gatewayv1.HTTPRoute{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github-egress"}}

	policy, err := constructExtProcPolicy(service, route, "aib-agentic-identity-broker-extproc", "aib-system", 50051)
	if err != nil {
		t.Fatalf("constructExtProcPolicy: %v", err)
	}
	targets, _, _ := unstructuredNestedSlice(policy.Object, "spec", "targetRefs")
	if len(targets) != 1 || targets[0].(map[string]any)["name"] != "github-egress" {
		t.Fatalf("targetRefs = %#v", targets)
	}
	extProc, _, _ := unstructuredNestedSlice(policy.Object, "spec", "extProc")
	entry := extProc[0].(map[string]any)
	if entry["failOpen"] != false {
		t.Fatalf("ext_proc is not fail closed: %#v", entry)
	}
	backend := entry["backendRefs"].([]any)[0].(map[string]any)
	if backend["name"] != "aib-agentic-identity-broker-extproc" || backend["namespace"] != "aib-system" || backend["port"] != int64(50051) {
		t.Fatalf("backendRef = %#v", backend)
	}
}

func TestExtProcInvariantRejectsEveryInternalRouteKind(t *testing.T) {
	service := &kaosv1alpha1.ThirdPartyService{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "forbidden"}}
	for _, kind := range []string{"Agent", "MCPServer", "ModelAPI", "MemoryStore"} {
		t.Run(kind, func(t *testing.T) {
			route := &gatewayv1.HTTPRoute{ObjectMeta: metav1.ObjectMeta{
				Namespace: "demo", Name: "internal",
				OwnerReferences: []metav1.OwnerReference{{APIVersion: kaosv1alpha1.GroupVersion.String(), Kind: kind, Name: "internal"}},
			}}
			policy, err := constructExtProcPolicy(service, route, "extproc", "aib-system", 50051)
			if err == nil || policy != nil {
				t.Fatalf("internal %s route accepted: policy=%#v err=%v", kind, policy, err)
			}
		})
	}
}

// Kept local to avoid hiding test assertions behind ignored accessor errors.
func unstructuredNestedSlice(object map[string]any, fields ...string) ([]any, bool, error) {
	current := any(object)
	for _, field := range fields {
		mapping, ok := current.(map[string]any)
		if !ok {
			return nil, false, nil
		}
		current, ok = mapping[field]
		if !ok {
			return nil, false, nil
		}
	}
	value, ok := current.([]any)
	return value, ok, nil
}
