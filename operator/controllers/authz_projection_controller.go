package controllers

import (
	"context"
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apiMeta "k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

// authzProjectionControllerName is the manager-registered name of the projection
// controller.
const authzProjectionControllerName = "kaos-authz-projection"

// authzSentinel is the single request key every KAOS resource change maps to. The
// projection is a whole-world function (agents reference other resources), so the
// controller funnels every event to one reconcile that recomputes the full state.
var authzSentinel = reconcile.Request{NamespacedName: types.NamespacedName{Namespace: "_kaos", Name: "_authz"}}

// PolicyProjector applies the projected desired state into a configured sink.
type PolicyProjector interface {
	Apply(ctx context.Context, desired projection.DesiredState) error
}

// AuthzProjectionReconciler projects KAOS resources into the configured identity
// and policy sinks. It recomputes the whole world on every change.
type AuthzProjectionReconciler struct {
	Client     client.Client
	Scheme     *runtime.Scheme
	Namespaces []string
	Projectors []PolicyProjector
	UserIssuer string
	Recorder   record.EventRecorder
}

//+kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=kaos.tools,resources=accessgrants,verbs=get;list;watch
//+kubebuilder:rbac:groups=kaos.tools,resources=accessgrants/status,verbs=get;update;patch

// SetupWithManager registers the controller. Every watched-resource change funnels
// to the sentinel request so bursts coalesce into a single whole-world reconcile.
// A generation-changed predicate filters out status-only updates and periodic
// resyncs, so the projection only recomputes when a spec that feeds it changes.
func (r *AuthzProjectionReconciler) SetupWithManager(mgr ctrl.Manager) error {
	toSentinel := handler.EnqueueRequestsFromMapFunc(func(context.Context, client.Object) []reconcile.Request {
		return []reconcile.Request{authzSentinel}
	})
	specChanged := builder.WithPredicates(predicate.GenerationChangedPredicate{})
	return builder.ControllerManagedBy(mgr).
		Named(authzProjectionControllerName).
		Watches(&kaosv1alpha1.Agent{}, toSentinel, specChanged).
		Watches(&kaosv1alpha1.MCPServer{}, toSentinel, specChanged).
		Watches(&kaosv1alpha1.ModelAPI{}, toSentinel, specChanged).
		Watches(&kaosv1alpha1.MemoryStore{}, toSentinel, specChanged).
		Watches(&kaosv1alpha1.AccessGrant{}, toSentinel, specChanged).
		Complete(r)
}

// Reconcile runs a full projection pass: list every KAOS resource, project the
// desired state, and apply it through every configured projector.
func (r *AuthzProjectionReconciler) Reconcile(ctx context.Context, _ reconcile.Request) (reconcile.Result, error) {
	resources, err := r.listResources(ctx)
	if err != nil {
		return reconcile.Result{}, fmt.Errorf("listing KAOS resources: %w", err)
	}
	desired := projection.Project(resources)
	accessGrants, err := r.listAccessGrants(ctx)
	if err != nil {
		return reconcile.Result{}, fmt.Errorf("listing AccessGrants: %w", err)
	}
	enforced := strings.TrimSpace(r.UserIssuer) != ""
	for i := range accessGrants {
		if err := r.updateAccessGrantStatus(ctx, &accessGrants[i], enforced); err != nil {
			return reconcile.Result{}, fmt.Errorf("updating AccessGrant %s/%s status: %w", accessGrants[i].Namespace, accessGrants[i].Name, err)
		}
		if enforced {
			desired.AccessGrants = append(desired.AccessGrants, accessGrantForProjection(&accessGrants[i]))
		}
	}
	for _, projector := range r.Projectors {
		if err := projector.Apply(ctx, desired); err != nil {
			return reconcile.Result{}, err
		}
	}
	return reconcile.Result{}, nil
}

// listResources reads every watched KAOS kind via the typed client and maps each
// object into the projection input.
func (r *AuthzProjectionReconciler) listResources(ctx context.Context) ([]projection.Resource, error) {
	namespaces := r.Namespaces
	if len(namespaces) == 0 {
		namespaces = []string{""} // cluster-wide
	}
	var out []projection.Resource
	for _, ns := range namespaces {
		var opts []client.ListOption
		if ns != "" {
			opts = append(opts, client.InNamespace(ns))
		}

		agents := &kaosv1alpha1.AgentList{}
		if err := r.Client.List(ctx, agents, opts...); err != nil {
			return nil, err
		}
		for i := range agents.Items {
			out = append(out, resourceFromAgent(&agents.Items[i]))
		}

		mcpServers := &kaosv1alpha1.MCPServerList{}
		if err := r.Client.List(ctx, mcpServers, opts...); err != nil {
			return nil, err
		}
		for i := range mcpServers.Items {
			out = append(out, projection.Resource{
				Kind:      projection.MCPServer.ResourceKind,
				Namespace: mcpServers.Items[i].Namespace,
				Name:      mcpServers.Items[i].Name,
				Labels:    mcpServers.Items[i].Labels,
			})
		}

		modelAPIs := &kaosv1alpha1.ModelAPIList{}
		if err := r.Client.List(ctx, modelAPIs, opts...); err != nil {
			return nil, err
		}
		for i := range modelAPIs.Items {
			out = append(out, projection.Resource{
				Kind:      projection.ModelAPI.ResourceKind,
				Namespace: modelAPIs.Items[i].Namespace,
				Name:      modelAPIs.Items[i].Name,
				Labels:    modelAPIs.Items[i].Labels,
			})
		}

		memoryStores := &kaosv1alpha1.MemoryStoreList{}
		if err := r.Client.List(ctx, memoryStores, opts...); err != nil {
			return nil, err
		}
		for i := range memoryStores.Items {
			out = append(out, projection.Resource{Kind: projection.MemoryStore.ResourceKind, Namespace: memoryStores.Items[i].Namespace, Name: memoryStores.Items[i].Name, Labels: memoryStores.Items[i].Labels})
		}
	}
	return out, nil
}

// resourceFromAgent extracts the projection-relevant fields from a typed Agent.
func resourceFromAgent(a *kaosv1alpha1.Agent) projection.Resource {
	res := projection.Resource{
		Kind:       projection.AgentKind,
		Namespace:  a.Namespace,
		Name:       a.Name,
		Labels:     a.Labels,
		MCPServers: a.Spec.MCPServers,
		ModelAPI:   a.Spec.ModelAPI,
	}
	if a.Spec.AgentNetwork != nil {
		res.Access = a.Spec.AgentNetwork.Access
	}
	if a.Spec.Config != nil && a.Spec.Config.Memory != nil {
		res.MemoryStore = a.Spec.Config.Memory.MemoryStore
	}
	return res
}

func (r *AuthzProjectionReconciler) listAccessGrants(ctx context.Context) ([]kaosv1alpha1.AccessGrant, error) {
	namespaces := r.Namespaces
	if len(namespaces) == 0 {
		namespaces = []string{""}
	}
	var out []kaosv1alpha1.AccessGrant
	for _, namespace := range namespaces {
		var opts []client.ListOption
		if namespace != "" {
			opts = append(opts, client.InNamespace(namespace))
		}
		list := &kaosv1alpha1.AccessGrantList{}
		if err := r.Client.List(ctx, list, opts...); err != nil {
			return nil, err
		}
		out = append(out, list.Items...)
	}
	return out, nil
}

func accessGrantForProjection(grant *kaosv1alpha1.AccessGrant) projection.AccessGrant {
	out := projection.AccessGrant{Namespace: grant.Namespace}
	for _, subject := range grant.Spec.Subjects {
		out.Subjects = append(out.Subjects, projection.AccessGrantSubject{Kind: string(subject.Kind), Name: subject.Name})
	}
	for _, resource := range grant.Spec.Resources {
		out.Resources = append(out.Resources, projection.AccessGrantResource{Kind: string(resource.Kind), Name: resource.Name, Selector: resource.Selector})
	}
	return out
}

func (r *AuthzProjectionReconciler) updateAccessGrantStatus(ctx context.Context, grant *kaosv1alpha1.AccessGrant, enforced bool) error {
	before := grant.DeepCopy()
	condition := metav1.Condition{Type: "Enforced", Status: metav1.ConditionTrue, Reason: "Enforced", Message: "AccessGrant is enforced by the configured user identity provider", ObservedGeneration: grant.Generation}
	if !enforced {
		condition.Status = metav1.ConditionFalse
		condition.Reason = "NoUserIdentityProvider"
		condition.Message = "A user identity provider must be configured for this AccessGrant to be enforced"
		if r.Recorder != nil {
			r.Recorder.Event(grant, corev1.EventTypeWarning, condition.Reason, condition.Message)
		}
	}
	apiMeta.SetStatusCondition(&grant.Status.Conditions, condition)
	return r.Client.Status().Patch(ctx, grant, client.MergeFrom(before))
}
