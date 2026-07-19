package security

import (
	"context"
	"testing"

	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
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

func TestConstructNetworkPolicyAllowsSameNamespacePods(t *testing.T) {
	np := constructNetworkPolicy(NetworkPolicyParams{
		Name:                       "modelapi-openai",
		Namespace:                  "default",
		PodSelector:                map[string]string{"app": "modelapi"},
		AllowedIngressPodSelectors: []map[string]string{{"app": "memorystore"}},
	}, Config{ExtAuthzURL: "svc:9191"})

	peers := np.Spec.Ingress[0].From
	if len(peers) != 3 {
		t.Fatalf("expected gateway, operator, and MemoryStore peers, got %d", len(peers))
	}
	if got := peers[2].PodSelector; got == nil || got.MatchLabels["app"] != "memorystore" {
		t.Fatalf("expected same-namespace app=memorystore peer, got %#v", got)
	}
	if peers[2].NamespaceSelector != nil {
		t.Fatalf("same-namespace peer must not select every pod in a namespace")
	}
}

func TestConstructNetworkPolicyEgressRules(t *testing.T) {
	cfg := Config{
		ExtAuthzURL:         "aib-ext-authz.aib-system.svc.cluster.local:9191",
		Issuer:              "http://aib-enduser.aib-system.svc.cluster.local:8000",
		GatewayNamespace:    "envoy-gateway-system",
		OperatorNamespace:   "kaos-system",
		NetworkPolicyEgress: true,
	}
	np := constructNetworkPolicy(NetworkPolicyParams{
		Name: "mcp-github", Namespace: "default", PodSelector: mcpPodSelector(),
	}, cfg)

	if !hasPolicyType(np, networkingv1.PolicyTypeIngress) || !hasPolicyType(np, networkingv1.PolicyTypeEgress) {
		t.Fatalf("expected ingress+egress PolicyTypes, got %#v", np.Spec.PolicyTypes)
	}
	if !hasDNSRule(np) {
		t.Fatalf("expected DNS egress rule with UDP+TCP 53, got %#v", np.Spec.Egress)
	}
	if !hasNamespaceEgress(np, "envoy-gateway-system") {
		t.Errorf("expected gateway namespace egress")
	}
	if !hasNamespaceEgress(np, "aib-system") {
		t.Errorf("expected AIB broker namespace egress")
	}
	if hasExternalEgress(np) {
		t.Errorf("non-ModelAPI policy should not allow external egress")
	}
}

func TestConstructNetworkPolicyModelAPIExternalEgress(t *testing.T) {
	cfg := Config{ExtAuthzURL: "svc:9191", NetworkPolicyEgress: true}
	np := constructNetworkPolicy(NetworkPolicyParams{
		Name: "modelapi-openai", Namespace: "default", PodSelector: map[string]string{"app": "modelapi"}, AllowExternalEgress: true,
	}, cfg)

	if !hasExternalEgress(np) {
		t.Fatalf("expected ModelAPI external egress allowance, got %#v", np.Spec.Egress)
	}
}

func hasPolicyType(np *networkingv1.NetworkPolicy, want networkingv1.PolicyType) bool {
	for _, got := range np.Spec.PolicyTypes {
		if got == want {
			return true
		}
	}
	return false
}

func hasNamespaceEgress(np *networkingv1.NetworkPolicy, namespace string) bool {
	for _, rule := range np.Spec.Egress {
		for _, peer := range rule.To {
			if peer.NamespaceSelector != nil && peer.NamespaceSelector.MatchLabels[namespaceNameLabel] == namespace {
				return true
			}
		}
	}
	return false
}

func hasDNSRule(np *networkingv1.NetworkPolicy) bool {
	for _, rule := range np.Spec.Egress {
		hasKubeSystem := false
		hasUDP := false
		hasTCP := false
		for _, peer := range rule.To {
			if peer.NamespaceSelector != nil && peer.NamespaceSelector.MatchLabels[namespaceNameLabel] == kubeSystemNamespace {
				hasKubeSystem = true
			}
		}
		for _, port := range rule.Ports {
			if port.Port != nil && port.Port.IntVal == 53 && port.Protocol != nil {
				switch *port.Protocol {
				case corev1.ProtocolUDP:
					hasUDP = true
				case corev1.ProtocolTCP:
					hasTCP = true
				}
			}
		}
		if hasKubeSystem && hasUDP && hasTCP {
			return true
		}
	}
	return false
}

func hasExternalEgress(np *networkingv1.NetworkPolicy) bool {
	for _, rule := range np.Spec.Egress {
		for _, peer := range rule.To {
			if peer.IPBlock != nil && peer.IPBlock.CIDR == "0.0.0.0/0" {
				return true
			}
		}
	}
	return false
}

func reconcileScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := corev1.AddToScheme(s); err != nil {
		t.Fatalf("add corev1: %v", err)
	}
	if err := networkingv1.AddToScheme(s); err != nil {
		t.Fatalf("add networkingv1: %v", err)
	}
	return s
}

func TestReconcileNetworkPolicyCreatesWhenOperational(t *testing.T) {
	scheme := reconcileScheme(t)
	owner := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "mcp-github", Namespace: "default", UID: "owner-uid"},
	}
	cl := fake.NewClientBuilder().WithScheme(scheme).WithObjects(owner).Build()

	cfg := Config{ExtAuthzURL: "svc:9191"}
	params := NetworkPolicyParams{
		Name: "mcp-github", Namespace: "default", PodSelector: mcpPodSelector(),
	}
	if err := ReconcileNetworkPolicy(context.Background(), cl, scheme, owner, params, cfg, logr.Discard()); err != nil {
		t.Fatalf("reconcile: %v", err)
	}

	got := &networkingv1.NetworkPolicy{}
	if err := cl.Get(context.Background(), types.NamespacedName{Name: "mcp-github", Namespace: "default"}, got); err != nil {
		t.Fatalf("expected NetworkPolicy to be created: %v", err)
	}
	if len(got.OwnerReferences) != 1 || got.OwnerReferences[0].UID != "owner-uid" {
		t.Errorf("expected controller owner reference, got %#v", got.OwnerReferences)
	}

	// Idempotent re-reconcile must not error.
	if err := ReconcileNetworkPolicy(context.Background(), cl, scheme, owner, params, cfg, logr.Discard()); err != nil {
		t.Fatalf("re-reconcile: %v", err)
	}
}

func TestReconcileNetworkPolicyCreatesWhenStrictStandalone(t *testing.T) {
	scheme := reconcileScheme(t)
	owner := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "mcp-github", Namespace: "default", UID: "owner-uid"},
	}
	cl := fake.NewClientBuilder().WithScheme(scheme).WithObjects(owner).Build()

	// No enforcement hook is configured; the strict switch alone must still
	// generate the bypass-prevention NetworkPolicy.
	cfg := Config{StrictGatewayAPI: true}
	params := NetworkPolicyParams{
		Name: "mcp-github", Namespace: "default", PodSelector: mcpPodSelector(),
	}
	if err := ReconcileNetworkPolicy(context.Background(), cl, scheme, owner, params, cfg, logr.Discard()); err != nil {
		t.Fatalf("reconcile: %v", err)
	}

	got := &networkingv1.NetworkPolicy{}
	if err := cl.Get(context.Background(), types.NamespacedName{Name: "mcp-github", Namespace: "default"}, got); err != nil {
		t.Fatalf("expected NetworkPolicy to be created under strict standalone config: %v", err)
	}
}

func TestReconcileNetworkPolicyNoopWhenNotEnabled(t *testing.T) {
	scheme := reconcileScheme(t)
	owner := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "mcp-github", Namespace: "default", UID: "owner-uid"},
	}
	cl := fake.NewClientBuilder().WithScheme(scheme).WithObjects(owner).Build()

	cases := map[string]Config{
		"not operational":     {ExtAuthzURL: ""},
		"operational but off": {ExtAuthzURL: "svc:9191", NetworkPolicyDisabled: true},
	}
	for name, cfg := range cases {
		t.Run(name, func(t *testing.T) {
			params := NetworkPolicyParams{Name: "mcp-github", Namespace: "default", PodSelector: mcpPodSelector()}
			if err := ReconcileNetworkPolicy(context.Background(), cl, scheme, owner, params, cfg, logr.Discard()); err != nil {
				t.Fatalf("reconcile: %v", err)
			}
			got := &networkingv1.NetworkPolicy{}
			err := cl.Get(context.Background(), types.NamespacedName{Name: "mcp-github", Namespace: "default"}, got)
			if !apierrors.IsNotFound(err) {
				t.Errorf("expected no NetworkPolicy, got err=%v", err)
			}
		})
	}
}
