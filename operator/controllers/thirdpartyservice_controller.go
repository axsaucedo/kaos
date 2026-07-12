package controllers

import (
	"context"
	"crypto/sha256"
	"fmt"

	apiMeta "k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

const (
	extensionPolicyGroup   = "gateway.envoyproxy.io"
	extensionPolicyVersion = "v1alpha1"
	extensionPolicyKind    = "EnvoyExtensionPolicy"
)

var extensionPolicyGVK = schema.GroupVersionKind{Group: extensionPolicyGroup, Version: extensionPolicyVersion, Kind: extensionPolicyKind}

// ThirdPartyServiceReconciler attaches token exchange only to declared egress routes.
type ThirdPartyServiceReconciler struct {
	client.Client
	Scheme               *runtime.Scheme
	TokenExchangeEnabled bool
	ExtProcServiceName   string
	ExtProcNamespace     string
	ExtProcPort          int
}

//+kubebuilder:rbac:groups=kaos.tools,resources=thirdpartyservices,verbs=get;list;watch
//+kubebuilder:rbac:groups=kaos.tools,resources=thirdpartyservices/status,verbs=get;update;patch

// Reconcile creates fail-closed ext_proc and the preceding JWT/ext_authz policy.
func (r *ThirdPartyServiceReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	service := &kaosv1alpha1.ThirdPartyService{}
	if err := r.Get(ctx, req.NamespacedName, service); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}
	policyName := service.Name + "-token-exchange"
	if !r.TokenExchangeEnabled {
		if err := r.deleteExtensionPolicy(ctx, service.Namespace, policyName); err != nil {
			return ctrl.Result{}, err
		}
		if err := r.deleteSecurityPolicy(ctx, service.Namespace, policyName); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{}, r.setReady(ctx, service, metav1.ConditionFalse, "FeatureDisabled", "Token exchange is disabled")
	}

	route := &gatewayv1.HTTPRoute{}
	routeKey := types.NamespacedName{Namespace: service.Namespace, Name: service.Spec.RouteRef.Name}
	if err := r.Get(ctx, routeKey, route); err != nil {
		_ = r.setReady(ctx, service, metav1.ConditionFalse, "RouteUnavailable", fmt.Sprintf("Dedicated third-party HTTPRoute %s is unavailable", routeKey))
		return ctrl.Result{}, err
	}
	if isInternalRoute(route) {
		if deleteErr := r.deleteExtensionPolicy(ctx, service.Namespace, policyName); deleteErr != nil {
			return ctrl.Result{}, deleteErr
		}
		err := fmt.Errorf("HTTPRoute %s is an operator-owned internal route; ext_proc attachment is forbidden", routeKey)
		_ = r.setReady(ctx, service, metav1.ConditionFalse, "InternalRouteForbidden", err.Error())
		return ctrl.Result{}, err
	}

	// EnvoyProxy.filterOrder (rendered by the chart) places ext_authz after
	// jwt_authn and ext_proc after ext_authz. Both route policies target this
	// same dedicated egress HTTPRoute.
	secCfg := security.GetConfig()
	if err := security.ReconcileSecurityPolicy(ctx, r.Client, r.Scheme, service, security.PolicyParams{
		Name: policyName, Namespace: service.Namespace, RouteName: route.Name,
		Labels: map[string]string{"kaos.tools/third-party-service": service.Name},
	}, secCfg, ctrl.LoggerFrom(ctx)); err != nil {
		return ctrl.Result{}, fmt.Errorf("reconciling JWT/ext_authz policy: %w", err)
	}
	desired, err := constructExtProcPolicy(service, route, r.ExtProcServiceName, r.ExtProcNamespace, r.ExtProcPort)
	if err != nil {
		return ctrl.Result{}, err
	}
	if err := r.reconcileExtensionPolicy(ctx, service, desired); err != nil {
		return ctrl.Result{}, err
	}
	if r.ExtProcNamespace != "" && r.ExtProcNamespace != service.Namespace {
		if err := reconcileExtProcReferenceGrant(ctx, r.Client, service.Namespace, r.ExtProcNamespace, r.ExtProcServiceName); err != nil {
			return ctrl.Result{}, err
		}
	}
	return ctrl.Result{}, r.setReady(ctx, service, metav1.ConditionTrue, "Attached", "AIB ext_proc is attached to the declared third-party egress route")
}

func constructExtProcPolicy(service *kaosv1alpha1.ThirdPartyService, route *gatewayv1.HTTPRoute, backendName, backendNamespace string, backendPort int) (*unstructured.Unstructured, error) {
	if isInternalRoute(route) {
		return nil, fmt.Errorf("ext_proc cannot target internal HTTPRoute %s/%s", route.Namespace, route.Name)
	}
	if backendName == "" || backendNamespace == "" || backendPort <= 0 {
		return nil, fmt.Errorf("AIB ext_proc backend is incomplete")
	}
	policy := &unstructured.Unstructured{}
	policy.SetGroupVersionKind(extensionPolicyGVK)
	policy.SetName(service.Name + "-token-exchange")
	policy.SetNamespace(service.Namespace)
	policy.SetLabels(map[string]string{"kaos.tools/third-party-service": service.Name})
	policy.Object["spec"] = map[string]any{
		"targetRefs": []any{map[string]any{"group": "gateway.networking.k8s.io", "kind": "HTTPRoute", "name": route.Name}},
		"extProc": []any{map[string]any{
			"backendRefs":    []any{map[string]any{"group": "", "kind": "Service", "name": backendName, "namespace": backendNamespace, "port": int64(backendPort)}},
			"failOpen":       false,
			"processingMode": map[string]any{"request": map[string]any{}},
		}},
	}
	// TODO(session B): the runtime must place the Keycloak re-minted user token
	// (sub=user, azp=agent DCR client, aud=token-exchange-broker) in
	// Authorization: Bearer on this declared egress call. AIB ext_proc replaces
	// that header with the user's third-party access token.
	return policy, nil
}

func isInternalRoute(route *gatewayv1.HTTPRoute) bool {
	internalKinds := map[string]bool{"Agent": true, "MCPServer": true, "ModelAPI": true, "MemoryStore": true}
	for _, owner := range route.OwnerReferences {
		if owner.APIVersion == kaosv1alpha1.GroupVersion.String() && internalKinds[owner.Kind] {
			return true
		}
	}
	return false
}

func (r *ThirdPartyServiceReconciler) reconcileExtensionPolicy(ctx context.Context, owner *kaosv1alpha1.ThirdPartyService, desired *unstructured.Unstructured) error {
	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(extensionPolicyGVK)
	key := types.NamespacedName{Namespace: desired.GetNamespace(), Name: desired.GetName()}
	err := r.Get(ctx, key, existing)
	if client.IgnoreNotFound(err) != nil {
		return err
	}
	if err != nil {
		if err := controllerutil.SetControllerReference(owner, desired, r.Scheme); err != nil {
			return err
		}
		return r.Create(ctx, desired)
	}
	spec, _, _ := unstructured.NestedMap(desired.Object, "spec")
	if err := unstructured.SetNestedMap(existing.Object, spec, "spec"); err != nil {
		return err
	}
	existing.SetLabels(desired.GetLabels())
	return r.Update(ctx, existing)
}

func (r *ThirdPartyServiceReconciler) deleteExtensionPolicy(ctx context.Context, namespace, name string) error {
	policy := &unstructured.Unstructured{}
	policy.SetGroupVersionKind(extensionPolicyGVK)
	policy.SetNamespace(namespace)
	policy.SetName(name)
	return client.IgnoreNotFound(r.Delete(ctx, policy))
}

func (r *ThirdPartyServiceReconciler) deleteSecurityPolicy(ctx context.Context, namespace, name string) error {
	policy := &unstructured.Unstructured{}
	policy.SetGroupVersionKind(security.SecurityPolicyGVK)
	policy.SetNamespace(namespace)
	policy.SetName(name)
	return client.IgnoreNotFound(r.Delete(ctx, policy))
}

func (r *ThirdPartyServiceReconciler) setReady(ctx context.Context, service *kaosv1alpha1.ThirdPartyService, status metav1.ConditionStatus, reason, message string) error {
	before := service.DeepCopy()
	if !apiMeta.SetStatusCondition(&service.Status.Conditions, metav1.Condition{
		Type: "Ready", Status: status, Reason: reason, Message: message, ObservedGeneration: service.Generation,
	}) {
		return nil
	}
	return r.Status().Patch(ctx, service, client.MergeFrom(before))
}

func reconcileExtProcReferenceGrant(ctx context.Context, c client.Client, sourceNamespace, backendNamespace, serviceName string) error {
	grant := &unstructured.Unstructured{}
	grant.SetGroupVersionKind(schema.GroupVersionKind{Group: "gateway.networking.k8s.io", Version: "v1beta1", Kind: "ReferenceGrant"})
	nameHash := sha256.Sum256([]byte(sourceNamespace + "\x00" + serviceName))
	grant.SetName(fmt.Sprintf("kaos-ext-proc-%x", nameHash[:6]))
	grant.SetNamespace(backendNamespace)
	grant.Object["spec"] = map[string]any{
		"from": []any{map[string]any{"group": extensionPolicyGroup, "kind": extensionPolicyKind, "namespace": sourceNamespace}},
		"to":   []any{map[string]any{"group": "", "kind": "Service", "name": serviceName}},
	}
	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(grant.GroupVersionKind())
	key := types.NamespacedName{Namespace: backendNamespace, Name: grant.GetName()}
	if err := c.Get(ctx, key, existing); err != nil {
		if client.IgnoreNotFound(err) != nil {
			return err
		}
		return c.Create(ctx, grant)
	}
	spec, _, _ := unstructured.NestedMap(grant.Object, "spec")
	_ = unstructured.SetNestedMap(existing.Object, spec, "spec")
	return c.Update(ctx, existing)
}

// SetupWithManager registers the ThirdPartyService controller and route watch.
func (r *ThirdPartyServiceReconciler) SetupWithManager(mgr ctrl.Manager) error {
	mapRoute := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, object client.Object) []reconcile.Request {
		services := &kaosv1alpha1.ThirdPartyServiceList{}
		if err := r.List(ctx, services, client.InNamespace(object.GetNamespace())); err != nil {
			return nil
		}
		var requests []reconcile.Request
		for i := range services.Items {
			if services.Items[i].Spec.RouteRef.Name == object.GetName() {
				requests = append(requests, reconcile.Request{NamespacedName: types.NamespacedName{Namespace: services.Items[i].Namespace, Name: services.Items[i].Name}})
			}
		}
		return requests
	})
	return ctrl.NewControllerManagedBy(mgr).
		For(&kaosv1alpha1.ThirdPartyService{}).
		Watches(&gatewayv1.HTTPRoute{}, mapRoute).
		Complete(r)
}
