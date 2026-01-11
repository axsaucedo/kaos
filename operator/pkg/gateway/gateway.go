// Package gateway provides utilities for Gateway API integration
package gateway

import (
	"context"
	"fmt"
	"os"

	"github.com/go-logr/logr"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"
)

// Config holds Gateway API configuration from environment
type Config struct {
	Enabled          bool
	GatewayName      string
	GatewayNamespace string
	// Default timeouts for each resource type (Gateway API Duration format)
	DefaultAgentTimeout    string
	DefaultModelAPITimeout string
	DefaultMCPTimeout      string
}

// Default timeout values (used when env vars are not set)
const (
	defaultAgentTimeout    = "120s" // Agents may do multi-step reasoning
	defaultModelAPITimeout = "120s" // LLM inference can take time
	defaultMCPTimeout      = "30s"  // Tool calls are typically fast
)

// GetConfig reads Gateway API configuration from environment variables
func GetConfig() Config {
	return Config{
		Enabled:                os.Getenv("GATEWAY_API_ENABLED") == "true",
		GatewayName:            os.Getenv("GATEWAY_NAME"),
		GatewayNamespace:       os.Getenv("GATEWAY_NAMESPACE"),
		DefaultAgentTimeout:    getEnvOrDefault("GATEWAY_DEFAULT_AGENT_TIMEOUT", defaultAgentTimeout),
		DefaultModelAPITimeout: getEnvOrDefault("GATEWAY_DEFAULT_MODELAPI_TIMEOUT", defaultModelAPITimeout),
		DefaultMCPTimeout:      getEnvOrDefault("GATEWAY_DEFAULT_MCP_TIMEOUT", defaultMCPTimeout),
	}
}

// getEnvOrDefault returns the value of an environment variable or a default value
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// ResourceType identifies the type of agentic resource
type ResourceType string

const (
	ResourceTypeAgent    ResourceType = "agent"
	ResourceTypeModelAPI ResourceType = "modelapi"
	ResourceTypeMCP      ResourceType = "mcp"
)

// HTTPRouteName generates a consistent name for an HTTPRoute
func HTTPRouteName(resourceType ResourceType, resourceName string) string {
	return fmt.Sprintf("%s-%s", resourceType, resourceName)
}

// HTTPRoutePath generates the path prefix for routing
// Format: /{namespace}/{resourceType}/{resourceName}
func HTTPRoutePath(namespace string, resourceType ResourceType, resourceName string) string {
	return fmt.Sprintf("/%s/%s/%s", namespace, resourceType, resourceName)
}

// GatewayEndpoint returns the external endpoint URL for a resource via Gateway
func GatewayEndpoint(gatewayHost string, namespace string, resourceType ResourceType, resourceName string) string {
	return fmt.Sprintf("http://%s/%s/%s/%s", gatewayHost, namespace, resourceType, resourceName)
}

// HTTPRouteParams holds parameters for creating an HTTPRoute
type HTTPRouteParams struct {
	ResourceType ResourceType
	ResourceName string
	Namespace    string
	ServiceName  string
	ServicePort  int32
	Labels       map[string]string
	// Timeout is the request timeout for the HTTPRoute (Gateway API Duration format, e.g., "30s", "1m")
	// If empty, a default timeout is applied based on resource type.
	Timeout string
}

// DefaultTimeout returns the default timeout for a resource type from config
func DefaultTimeout(resourceType ResourceType) string {
	config := GetConfig()
	switch resourceType {
	case ResourceTypeModelAPI:
		return config.DefaultModelAPITimeout
	case ResourceTypeAgent:
		return config.DefaultAgentTimeout
	case ResourceTypeMCP:
		return config.DefaultMCPTimeout
	default:
		return config.DefaultMCPTimeout
	}
}

// constructHTTPRoute creates an HTTPRoute for a resource (internal helper)
func constructHTTPRoute(params HTTPRouteParams, config Config) *gatewayv1.HTTPRoute {
	pathPrefix := gatewayv1.PathMatchPathPrefix
	pathValue := HTTPRoutePath(params.Namespace, params.ResourceType, params.ResourceName)
	port := gatewayv1.PortNumber(params.ServicePort)
	gwNamespace := gatewayv1.Namespace(config.GatewayNamespace)

	// URL rewrite to strip the path prefix
	rewritePath := "/"

	// Determine timeout - use provided value or default
	timeout := params.Timeout
	if timeout == "" {
		timeout = DefaultTimeout(params.ResourceType)
	}

	// Build the HTTPRoute rule
	rule := gatewayv1.HTTPRouteRule{
		Matches: []gatewayv1.HTTPRouteMatch{
			{
				Path: &gatewayv1.HTTPPathMatch{
					Type:  &pathPrefix,
					Value: &pathValue,
				},
			},
		},
		Filters: []gatewayv1.HTTPRouteFilter{
			{
				Type: gatewayv1.HTTPRouteFilterURLRewrite,
				URLRewrite: &gatewayv1.HTTPURLRewriteFilter{
					Path: &gatewayv1.HTTPPathModifier{
						Type:               gatewayv1.PrefixMatchHTTPPathModifier,
						ReplacePrefixMatch: &rewritePath,
					},
				},
			},
		},
		BackendRefs: []gatewayv1.HTTPBackendRef{
			{
				BackendRef: gatewayv1.BackendRef{
					BackendObjectReference: gatewayv1.BackendObjectReference{
						Name: gatewayv1.ObjectName(params.ServiceName),
						Port: &port,
					},
				},
			},
		},
	}

	// Add timeout if not "0s" (which means use gateway default)
	if timeout != "0s" && timeout != "" {
		requestTimeout := gatewayv1.Duration(timeout)
		rule.Timeouts = &gatewayv1.HTTPRouteTimeouts{
			Request: &requestTimeout,
		}
	}

	return &gatewayv1.HTTPRoute{
		ObjectMeta: metav1.ObjectMeta{
			Name:      HTTPRouteName(params.ResourceType, params.ResourceName),
			Namespace: params.Namespace,
			Labels:    params.Labels,
		},
		Spec: gatewayv1.HTTPRouteSpec{
			CommonRouteSpec: gatewayv1.CommonRouteSpec{
				ParentRefs: []gatewayv1.ParentReference{
					{
						Name:      gatewayv1.ObjectName(config.GatewayName),
						Namespace: &gwNamespace,
					},
				},
			},
			Rules: []gatewayv1.HTTPRouteRule{rule},
		},
	}
}

// ReconcileHTTPRoute creates or updates an HTTPRoute for a resource.
// This consolidates the common reconciliation logic used by all controllers.
func ReconcileHTTPRoute(
	ctx context.Context,
	c client.Client,
	scheme *runtime.Scheme,
	owner client.Object,
	params HTTPRouteParams,
	log logr.Logger,
) error {
	config := GetConfig()
	if !config.Enabled {
		return nil
	}

	httpRoute := constructHTTPRoute(params, config)

	existing := &gatewayv1.HTTPRoute{}
	err := c.Get(ctx, types.NamespacedName{Name: httpRoute.Name, Namespace: httpRoute.Namespace}, existing)

	if err != nil && apierrors.IsNotFound(err) {
		if err := controllerutil.SetControllerReference(owner, httpRoute, scheme); err != nil {
			return err
		}
		log.Info("Creating HTTPRoute", "name", httpRoute.Name)
		return c.Create(ctx, httpRoute)
	} else if err != nil {
		return err
	}

	existing.Spec = httpRoute.Spec
	return c.Update(ctx, existing)
}
