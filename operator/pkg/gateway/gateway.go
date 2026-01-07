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
}

// GetConfig reads Gateway API configuration from environment variables
func GetConfig() Config {
	return Config{
		Enabled:          os.Getenv("GATEWAY_API_ENABLED") == "true",
		GatewayName:      os.Getenv("GATEWAY_NAME"),
		GatewayNamespace: os.Getenv("GATEWAY_NAMESPACE"),
	}
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
}

// constructHTTPRoute creates an HTTPRoute for a resource (internal helper)
func constructHTTPRoute(params HTTPRouteParams, config Config) *gatewayv1.HTTPRoute {
	pathPrefix := gatewayv1.PathMatchPathPrefix
	pathValue := HTTPRoutePath(params.Namespace, params.ResourceType, params.ResourceName)
	port := gatewayv1.PortNumber(params.ServicePort)
	gwNamespace := gatewayv1.Namespace(config.GatewayNamespace)

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
			Rules: []gatewayv1.HTTPRouteRule{
				{
					Matches: []gatewayv1.HTTPRouteMatch{
						{
							Path: &gatewayv1.HTTPPathMatch{
								Type:  &pathPrefix,
								Value: &pathValue,
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
				},
			},
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
