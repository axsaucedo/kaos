package security

import (
	"context"
	"fmt"

	"github.com/go-logr/logr"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

// namespaceNameLabel is the well-known label Kubernetes stamps on every
// Namespace, holding the namespace's own name. It is used by NetworkPolicy
// namespaceSelectors to allow ingress from specific namespaces.
const namespaceNameLabel = "kubernetes.io/metadata.name"

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
}

// constructNetworkPolicy builds a typed NetworkPolicy that denies direct
// workload-to-workload application traffic to the selected pods, allowing
// ingress only from the Envoy Gateway data-plane namespace (so the Gateway can
// route requests) and from the operator namespace (so the operator can poll
// ClusterIP status endpoints). Selecting the pods with PolicyTypes [Ingress] and
// only these explicit allow-from rules yields a default-deny ingress baseline for
// the workload, closing the gateway-bypass path. Egress is intentionally not
// restricted in this policy: workloads still need DNS, registry, gateway, broker,
// and (for ModelAPI) external-provider egress.
func constructNetworkPolicy(params NetworkPolicyParams, cfg Config) *networkingv1.NetworkPolicy {
	gatewayNS := cfg.GatewayNamespaceOrDefault()
	operatorNS := cfg.OperatorNamespaceOrDefault()

	from := []networkingv1.NetworkPolicyPeer{
		{
			NamespaceSelector: &metav1.LabelSelector{
				MatchLabels: map[string]string{namespaceNameLabel: gatewayNS},
			},
		},
	}
	// Avoid emitting a duplicate peer when the operator shares the gateway namespace.
	if operatorNS != gatewayNS {
		from = append(from, networkingv1.NetworkPolicyPeer{
			NamespaceSelector: &metav1.LabelSelector{
				MatchLabels: map[string]string{namespaceNameLabel: operatorNS},
			},
		})
	}

	return &networkingv1.NetworkPolicy{
		ObjectMeta: metav1.ObjectMeta{
			Name:      params.Name,
			Namespace: params.Namespace,
			Labels:    params.Labels,
		},
		Spec: networkingv1.NetworkPolicySpec{
			PodSelector: metav1.LabelSelector{MatchLabels: params.PodSelector},
			PolicyTypes: []networkingv1.PolicyType{networkingv1.PolicyTypeIngress},
			Ingress: []networkingv1.NetworkPolicyIngressRule{
				{From: from},
			},
		},
	}
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
