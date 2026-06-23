package security

import (
	"testing"

	networkingv1 "k8s.io/api/networking/v1"
)

func mcpPodSelector() map[string]string {
	return map[string]string{"app": "mcpserver", "mcpserver": "github"}
}

func TestConstructNetworkPolicyShape(t *testing.T) {
	cfg := Config{
		ExtAuthzURL:       "aib-access-check.kaos-system.svc.cluster.local:9191",
		GatewayNamespace:  "envoy-gateway-system",
		OperatorNamespace: "kaos-system",
	}
	params := NetworkPolicyParams{
		Name:        "mcp-github",
		Namespace:   "default",
		PodSelector: mcpPodSelector(),
		Labels:      map[string]string{"app": "kaos"},
	}

	np := constructNetworkPolicy(params, cfg)

	if np.Name != "mcp-github" || np.Namespace != "default" {
		t.Fatalf("unexpected name/namespace %s/%s", np.Name, np.Namespace)
	}
	if np.Labels["app"] != "kaos" {
		t.Errorf("expected app=kaos label")
	}
	if got := np.Spec.PodSelector.MatchLabels; got["app"] != "mcpserver" || got["mcpserver"] != "github" {
		t.Errorf("unexpected podSelector %#v", got)
	}
	if len(np.Spec.PolicyTypes) != 1 || np.Spec.PolicyTypes[0] != networkingv1.PolicyTypeIngress {
		t.Fatalf("expected PolicyTypes [Ingress], got %#v", np.Spec.PolicyTypes)
	}
	if len(np.Spec.Ingress) != 1 {
		t.Fatalf("expected one ingress rule, got %d", len(np.Spec.Ingress))
	}
	if len(np.Spec.Egress) != 0 {
		t.Errorf("expected no egress rules, got %d", len(np.Spec.Egress))
	}

	peers := np.Spec.Ingress[0].From
	if len(peers) != 2 {
		t.Fatalf("expected two ingress peers (gateway + operator), got %d", len(peers))
	}
	got := map[string]bool{}
	for _, p := range peers {
		if p.NamespaceSelector == nil {
			t.Fatalf("expected namespaceSelector peer, got %#v", p)
		}
		got[p.NamespaceSelector.MatchLabels[namespaceNameLabel]] = true
	}
	if !got["envoy-gateway-system"] || !got["kaos-system"] {
		t.Errorf("expected gateway + operator namespaces, got %#v", got)
	}
}

func TestConstructNetworkPolicyDeduplicatesSharedNamespace(t *testing.T) {
	cfg := Config{
		ExtAuthzURL:       "svc:9191",
		GatewayNamespace:  "shared",
		OperatorNamespace: "shared",
	}
	np := constructNetworkPolicy(NetworkPolicyParams{
		Name: "a", Namespace: "default", PodSelector: mcpPodSelector(),
	}, cfg)

	if peers := np.Spec.Ingress[0].From; len(peers) != 1 {
		t.Fatalf("expected a single deduplicated peer, got %d", len(peers))
	}
}

func TestConstructNetworkPolicyDefaultNamespaces(t *testing.T) {
	cfg := Config{ExtAuthzURL: "svc:9191"}
	np := constructNetworkPolicy(NetworkPolicyParams{
		Name: "a", Namespace: "default", PodSelector: mcpPodSelector(),
	}, cfg)

	got := map[string]bool{}
	for _, p := range np.Spec.Ingress[0].From {
		got[p.NamespaceSelector.MatchLabels[namespaceNameLabel]] = true
	}
	if !got[defaultGatewayNamespace] || !got[defaultOperatorNamespace] {
		t.Errorf("expected default namespaces %q/%q, got %#v",
			defaultGatewayNamespace, defaultOperatorNamespace, got)
	}
}
