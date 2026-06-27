package security

import (
	"context"
	"fmt"
	"strings"

	"github.com/go-logr/logr"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

// Envoy Gateway SecurityPolicy group/version/kind used to attach external
// authorization to a route.
const (
	securityPolicyGroup   = "gateway.envoyproxy.io"
	securityPolicyVersion = "v1alpha1"
	securityPolicyKind    = "SecurityPolicy"
	httpRouteGroup        = "gateway.networking.k8s.io"
	httpRouteKind         = "HTTPRoute"
)

// SecurityPolicyGVK is the GroupVersionKind of the generated SecurityPolicy.
var SecurityPolicyGVK = schema.GroupVersionKind{
	Group:   securityPolicyGroup,
	Version: securityPolicyVersion,
	Kind:    securityPolicyKind,
}

// PolicyParams describes the protected route a SecurityPolicy should guard.
type PolicyParams struct {
	// Name is the SecurityPolicy name (typically the guarded HTTPRoute's name).
	Name string
	// Namespace is the namespace of the SecurityPolicy and the target route.
	Namespace string
	// RouteName is the name of the HTTPRoute the policy targets.
	RouteName string
	// Labels are applied to the generated SecurityPolicy.
	Labels map[string]string
}

// constructSecurityPolicy builds an Envoy Gateway SecurityPolicy (as an
// unstructured object) that attaches a fail-closed gRPC external authorization
// check to the target HTTPRoute. The check is performed by the configured
// access-check backend Service. It returns an error if the configured ext_authz
// URL cannot be resolved to a Service backend reference.
func constructSecurityPolicy(params PolicyParams, cfg Config) (*unstructured.Unstructured, error) {
	name, namespace, port, err := cfg.ExtAuthzBackendRef()
	if err != nil {
		return nil, err
	}

	policy := &unstructured.Unstructured{}
	policy.SetGroupVersionKind(SecurityPolicyGVK)
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

	_ = unstructured.SetNestedMap(policy.Object, map[string]interface{}{
		"failOpen": false,
		"headersToExtAuth": []interface{}{
			"authorization",
			"x-agent-authorization",
		},
		"grpc": map[string]interface{}{
			"backendRef": backendRef,
		},
	}, "spec", "extAuth")

	if cfg.JWTEnabled() {
		if providers := constructJWTProviders(cfg); len(providers) > 0 {
			_ = unstructured.SetNestedSlice(policy.Object, providers, "spec", "jwt", "providers")
		}
	}

	return policy, nil
}

// constructJWTProviders builds the Envoy Gateway SecurityPolicy spec.jwt.providers
// list. The agent (actor) provider verifies the broker-issued token carried on the
// x-agent-authorization header and is emitted whenever an agent issuer is set. The
// user (subject) provider verifies the human token on the standard Authorization
// header and is emitted only when a user issuer is configured; autonomous, actor-only
// requests carry no user token, so the user provider must tolerate its absence. Each
// provider maps identity claims to trusted headers for downstream ext_authz and audit.
func constructJWTProviders(cfg Config) []interface{} {
	providers := make([]interface{}, 0, 2)

	if agentJWKS := cfg.AgentJWKSURI(); agentJWKS != "" {
		providers = append(providers, map[string]interface{}{
			"name":   "agent",
			"issuer": strings.TrimSpace(cfg.Issuer),
			"remoteJWKS": map[string]interface{}{
				"uri": agentJWKS,
			},
			"extractFrom": map[string]interface{}{
				"headers": []interface{}{
					map[string]interface{}{
						"name":        "x-agent-authorization",
						"valuePrefix": "Bearer ",
					},
				},
			},
			"claimToHeaders": []interface{}{
				map[string]interface{}{"claim": "sub", "header": "x-agent-claim-sub"},
			},
		})
	}

	if userJWKS := cfg.UserJWKSURI(); userJWKS != "" {
		userProvider := map[string]interface{}{
			"name":   "user",
			"issuer": strings.TrimSpace(cfg.UserIssuer),
			"remoteJWKS": map[string]interface{}{
				"uri": userJWKS,
			},
			"claimToHeaders": []interface{}{
				map[string]interface{}{"claim": "sub", "header": "x-user-claim-sub"},
				map[string]interface{}{"claim": "preferred_username", "header": "x-user-claim-username"},
			},
		}
		if audience := strings.TrimSpace(cfg.UserAudience); audience != "" {
			userProvider["audiences"] = []interface{}{audience}
		}
		providers = append(providers, userProvider)
	}

	return providers
}

// ReconcileSecurityPolicy creates or updates the SecurityPolicy that guards a
// protected route. It is a no-op unless authorization is enabled and the
// external authorization backend is fully specified.
func ReconcileSecurityPolicy(
	ctx context.Context,
	c client.Client,
	scheme *runtime.Scheme,
	owner client.Object,
	params PolicyParams,
	cfg Config,
	log logr.Logger,
) error {
	if !cfg.IsOperational() {
		return nil
	}

	desired, err := constructSecurityPolicy(params, cfg)
	if err != nil {
		return fmt.Errorf("construct SecurityPolicy: %w", err)
	}

	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(SecurityPolicyGVK)
	err = c.Get(ctx, types.NamespacedName{Name: params.Name, Namespace: params.Namespace}, existing)
	if err != nil && apierrors.IsNotFound(err) {
		if err := controllerutil.SetControllerReference(owner, desired, scheme); err != nil {
			return fmt.Errorf("set controller reference on SecurityPolicy: %w", err)
		}
		log.Info("Creating SecurityPolicy", "name", params.Name, "namespace", params.Namespace)
		return c.Create(ctx, desired)
	} else if err != nil {
		return err
	}

	spec, _, _ := unstructured.NestedMap(desired.Object, "spec")
	if err := unstructured.SetNestedMap(existing.Object, spec, "spec"); err != nil {
		return fmt.Errorf("update SecurityPolicy spec: %w", err)
	}
	return c.Update(ctx, existing)
}
