package security

import (
	"context"
	"fmt"

	"github.com/go-logr/logr"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

// Envoy Gateway EnvoyExtensionPolicy group/version/kind used to attach an
// external-processing (ext_proc) token-exchange filter to a route. The group
// and version match the SecurityPolicy CRD (gateway.envoyproxy.io/v1alpha1);
// the verified field shape is from Envoy Gateway v1.4.6.
const envoyExtensionPolicyKind = "EnvoyExtensionPolicy"

// EnvoyExtensionPolicyGVK is the GroupVersionKind of the generated
// EnvoyExtensionPolicy.
var EnvoyExtensionPolicyGVK = schema.GroupVersionKind{
	Group:   securityPolicyGroup,
	Version: securityPolicyVersion,
	Kind:    envoyExtensionPolicyKind,
}

// constructEnvoyExtensionPolicy builds an Envoy Gateway EnvoyExtensionPolicy (as
// an unstructured object) that attaches the AIB ext_proc token-exchange service
// to the target HTTPRoute. The filter runs after ext_authz in the gateway
// pipeline; it inspects request headers and, when a delegated third-party token
// is needed, replaces the upstream Authorization header with an exchanged token.
// Only request headers are sent to the processor (no body), which is sufficient
// for the header-based RFC 8693 exchange. It returns an error if the configured
// ext_proc URL cannot be resolved to a Service backend reference.
func constructEnvoyExtensionPolicy(params PolicyParams, cfg Config) (*unstructured.Unstructured, error) {
	name, namespace, port, err := cfg.ExtProcBackendRef()
	if err != nil {
		return nil, err
	}

	policy := &unstructured.Unstructured{}
	policy.SetGroupVersionKind(EnvoyExtensionPolicyGVK)
	policy.SetName(params.Name)
	policy.SetNamespace(params.Namespace)
	if len(params.Labels) > 0 {
		policy.SetLabels(params.Labels)
	}

	_ = unstructured.SetNestedSlice(policy.Object, []interface{}{
		map[string]interface{}{
			"group": httpRouteGroup,
			"kind":  httpRouteKind,
			"name":  params.RouteName,
		},
	}, "spec", "targetRefs")

	backendRef := map[string]interface{}{
		"group": "",
		"kind":  "Service",
		"name":  name,
		"port":  int64(port),
	}
	if namespace != "" {
		backendRef["namespace"] = namespace
	}

	_ = unstructured.SetNestedSlice(policy.Object, []interface{}{
		map[string]interface{}{
			"backendRefs": []interface{}{backendRef},
			"processingMode": map[string]interface{}{
				"request": map[string]interface{}{},
			},
		},
	}, "spec", "extProc")

	return policy, nil
}

// ReconcileEnvoyExtensionPolicy creates or updates the EnvoyExtensionPolicy that
// attaches ext_proc token exchange to a protected route. It is a no-op unless
// token exchange is enabled (cfg.ExtProcEnabled()).
func ReconcileEnvoyExtensionPolicy(
	ctx context.Context,
	c client.Client,
	scheme *runtime.Scheme,
	owner client.Object,
	params PolicyParams,
	cfg Config,
	log logr.Logger,
) error {
	if !cfg.ExtProcEnabled() {
		return nil
	}

	desired, err := constructEnvoyExtensionPolicy(params, cfg)
	if err != nil {
		return fmt.Errorf("construct EnvoyExtensionPolicy: %w", err)
	}

	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(EnvoyExtensionPolicyGVK)
	err = c.Get(ctx, types.NamespacedName{Name: params.Name, Namespace: params.Namespace}, existing)
	if err != nil && apierrors.IsNotFound(err) {
		if err := controllerutil.SetControllerReference(owner, desired, scheme); err != nil {
			return fmt.Errorf("set controller reference on EnvoyExtensionPolicy: %w", err)
		}
		log.Info("Creating EnvoyExtensionPolicy", "name", params.Name, "namespace", params.Namespace)
		return c.Create(ctx, desired)
	} else if err != nil {
		return err
	}

	spec, _, _ := unstructured.NestedMap(desired.Object, "spec")
	if err := unstructured.SetNestedMap(existing.Object, spec, "spec"); err != nil {
		return fmt.Errorf("update EnvoyExtensionPolicy spec: %w", err)
	}
	return c.Update(ctx, existing)
}
