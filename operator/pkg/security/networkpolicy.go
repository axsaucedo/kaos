package security

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

// namespaceNameLabel is the well-known label Kubernetes stamps on every
// Namespace, holding the namespace's own name. It is used by NetworkPolicy
// namespaceSelectors to allow ingress from specific namespaces.
const namespaceNameLabel = "kubernetes.io/metadata.name"

const kubeSystemNamespace = "kube-system"

// NetworkPolicyParams describes the protected workload a NetworkPolicy should
// guard.
type NetworkPolicyParams struct {
	// Name is the NetworkPolicy name (typically the workload's route name).
	Name string
	// Namespace is the namespace of the NetworkPolicy and the target workload.
	Namespace string
	// PodSelector selects the protected workload's pods (e.g. {"app":"mcpserver","mcpserver":name}).
	PodSelector map[string]string
	// Labels are applied to the generated NetworkPolicy.
	Labels map[string]string
	// AllowedIngressPodSelectors admit same-namespace workload clients without
	// opening direct access to every pod in the namespace.
	AllowedIngressPodSelectors []map[string]string
	// AllowExternalEgress permits provider-facing egress that cannot be enumerated
	// by namespace. Set only for ModelAPI workloads that proxy to external LLMs.
	AllowExternalEgress bool
}

// constructNetworkPolicy builds a typed NetworkPolicy that denies direct
// workload-to-workload application traffic to the selected pods, allowing
// ingress only from the Envoy Gateway data-plane namespace (so the Gateway can
// route requests) and from the operator namespace (so the operator can poll
// ClusterIP status endpoints). Selecting the pods with PolicyTypes [Ingress] and
// only these explicit allow-from rules yields a default-deny ingress baseline for
// the workload, closing the gateway-bypass path. When the separately gated egress
// dimension is enabled, egress is restricted to DNS plus the gateway/control-plane
// namespaces; ModelAPI workloads additionally allow external egress so provider
// calls keep working even though provider IP ranges cannot be enumerated safely.
func constructNetworkPolicy(params NetworkPolicyParams, cfg Config) *networkingv1.NetworkPolicy {
	gatewayNS := cfg.GatewayNamespaceOrDefault()
	operatorNS := cfg.OperatorNamespaceOrDefault()

	from := []networkingv1.NetworkPolicyPeer{namespacePeer(gatewayNS)}
	// Avoid emitting a duplicate peer when the operator shares the gateway namespace.
	if operatorNS != gatewayNS {
		from = append(from, namespacePeer(operatorNS))
	}
	for _, selector := range params.AllowedIngressPodSelectors {
		if len(selector) > 0 {
			from = append(from, networkingv1.NetworkPolicyPeer{
				PodSelector: &metav1.LabelSelector{MatchLabels: selector},
			})
		}
	}

	policyTypes := []networkingv1.PolicyType{networkingv1.PolicyTypeIngress}
	var egress []networkingv1.NetworkPolicyEgressRule
	if cfg.NetworkPolicyEgressEnabled() {
		policyTypes = append(policyTypes, networkingv1.PolicyTypeEgress)
		egress = constructEgressRules(params, cfg)
	}

	return &networkingv1.NetworkPolicy{
		ObjectMeta: metav1.ObjectMeta{
			Name:      params.Name,
			Namespace: params.Namespace,
			Labels:    params.Labels,
		},
		Spec: networkingv1.NetworkPolicySpec{
			PodSelector: metav1.LabelSelector{MatchLabels: params.PodSelector},
			PolicyTypes: policyTypes,
			Ingress: []networkingv1.NetworkPolicyIngressRule{
				{From: from},
			},
			Egress: egress,
		},
	}
}

func constructEgressRules(params NetworkPolicyParams, cfg Config) []networkingv1.NetworkPolicyEgressRule {
	dnsUDP := corev1.ProtocolUDP
	dnsTCP := corev1.ProtocolTCP
	dnsPort := intstr.FromInt(53)

	rules := []networkingv1.NetworkPolicyEgressRule{
		{
			To: []networkingv1.NetworkPolicyPeer{namespacePeer(kubeSystemNamespace)},
			Ports: []networkingv1.NetworkPolicyPort{
				{Protocol: &dnsUDP, Port: &dnsPort},
				{Protocol: &dnsTCP, Port: &dnsPort},
			},
		},
	}

	allowedNamespaces := []string{
		cfg.GatewayNamespaceOrDefault(),
		cfg.OperatorNamespaceOrDefault(),
	}
	for _, endpoint := range []string{cfg.Issuer, cfg.ExtAuthzURL} {
		if ns := serviceNamespaceFromEndpoint(endpoint); ns != "" {
			allowedNamespaces = append(allowedNamespaces, ns)
		}
	}
	// AIB broker/ext_authz namespaces are derived from configured Service
	// DNS endpoints so token minting and gateway policy backends remain reachable.
	for _, ns := range deduplicateStrings(allowedNamespaces) {
		rules = append(rules, networkingv1.NetworkPolicyEgressRule{
			To: []networkingv1.NetworkPolicyPeer{namespacePeer(ns)},
		})
	}

	if params.AllowExternalEgress {
		// ModelAPI proxies call arbitrary LLM provider endpoints whose IP ranges vary
		// by provider and region. Allowing 0.0.0.0/0 avoids silently breaking those
		// providers while non-ModelAPI workloads remain namespace-restricted.
		rules = append(rules, networkingv1.NetworkPolicyEgressRule{
			To: []networkingv1.NetworkPolicyPeer{
				{IPBlock: &networkingv1.IPBlock{CIDR: "0.0.0.0/0"}},
			},
		})
	}

	return rules
}

func namespacePeer(namespace string) networkingv1.NetworkPolicyPeer {
	return networkingv1.NetworkPolicyPeer{
		NamespaceSelector: &metav1.LabelSelector{
			MatchLabels: map[string]string{namespaceNameLabel: namespace},
		},
	}
}

func deduplicateStrings(values []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		out = append(out, value)
	}
	return out
}

func serviceNamespaceFromEndpoint(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	host := raw
	if strings.Contains(raw, "://") {
		parsed, err := url.Parse(raw)
		if err != nil {
			return ""
		}
		host = parsed.Host
	}
	host, _, _ = strings.Cut(host, ":")
	labels := strings.Split(host, ".")
	if len(labels) < 2 {
		return ""
	}
	return labels[1]
}

// ReconcileNetworkPolicy creates or updates the NetworkPolicy that prevents the
// Gateway from being bypassed for a protected workload. It is a no-op unless
// NetworkPolicy generation is enabled (security operational and not disabled).
func ReconcileNetworkPolicy(
	ctx context.Context,
	c client.Client,
	scheme *runtime.Scheme,
	owner client.Object,
	params NetworkPolicyParams,
	cfg Config,
	log logr.Logger,
) error {
	if !cfg.NetworkPolicyEnabled() {
		return nil
	}

	desired := constructNetworkPolicy(params, cfg)

	existing := &networkingv1.NetworkPolicy{}
	err := c.Get(ctx, types.NamespacedName{Name: params.Name, Namespace: params.Namespace}, existing)
	if err != nil && apierrors.IsNotFound(err) {
		if err := controllerutil.SetControllerReference(owner, desired, scheme); err != nil {
			return fmt.Errorf("set controller reference on NetworkPolicy: %w", err)
		}
		log.Info("Creating NetworkPolicy", "name", params.Name, "namespace", params.Namespace)
		return c.Create(ctx, desired)
	} else if err != nil {
		return err
	}

	existing.Spec = desired.Spec
	if len(desired.Labels) > 0 {
		existing.Labels = desired.Labels
	}
	return c.Update(ctx, existing)
}
