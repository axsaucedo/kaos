package controllers

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/aib"
	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

// aibManagedBy labels the credential Secrets provisioned by the projection
// controller so they can be pruned when their agent is gone.
const aibManagedBy = "kaos-operator-aib"

// aibSentinel is the single request key every KAOS resource change maps to. The
// projection is a whole-world function (agents reference other resources), so the
// controller funnels every event to one reconcile that recomputes the full state.
var aibSentinel = reconcile.Request{NamespacedName: types.NamespacedName{Namespace: "_kaos", Name: "_aib"}}

// AIBAdmin is the subset of the AIB admin client the projection reconciler needs.
// It is an interface so the reconciler can be unit tested with a fake; it is
// satisfied directly by *aib.Client.
type AIBAdmin interface {
	List(ctx context.Context, collection string) ([]map[string]any, error)
	CreateOrGet(ctx context.Context, collection, matchField, matchValue string, body map[string]any) (string, error)
	Delete(ctx context.Context, collection, id string) (bool, error)
	MintCredentials(ctx context.Context, agentID string) (aib.Credentials, error)
}

// AIBProjectionReconciler projects KAOS resources into the Agentic Identity
// Broker and provisions per-agent credential Secrets. It is the operator's only
// caller of the AIB admin API and the only minter/writer of credential Secrets;
// the workload reconcilers never talk to the broker. Because it recomputes the
// whole world on every change it runs independently of the workload controllers,
// so a broker outage stalls only projection and never workload reconciliation.
type AIBProjectionReconciler struct {
	Client       client.Client
	Scheme       *runtime.Scheme
	AIB          AIBAdmin
	Namespaces   []string
	SecretPrefix string
	Prune        bool
}

//+kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch;create;update;patch;delete

// SetupWithManager registers the controller, watching the three KAOS kinds and
// funnelling every event to the sentinel request so bursts coalesce into one full
// reconcile.
func (r *AIBProjectionReconciler) SetupWithManager(mgr ctrl.Manager) error {
	toSentinel := handler.EnqueueRequestsFromMapFunc(func(context.Context, client.Object) []reconcile.Request {
		return []reconcile.Request{aibSentinel}
	})
	return builder.ControllerManagedBy(mgr).
		Named("kaos-aib-projection").
		Watches(&kaosv1alpha1.Agent{}, toSentinel).
		Watches(&kaosv1alpha1.MCPServer{}, toSentinel).
		Watches(&kaosv1alpha1.ModelAPI{}, toSentinel).
		Complete(r)
}

// Reconcile runs a full projection pass: list every KAOS resource, project the
// desired AIB state, apply it, and provision credential Secrets. Returning an
// error requeues the sentinel with backoff, so transient broker failures retry.
func (r *AIBProjectionReconciler) Reconcile(ctx context.Context, _ reconcile.Request) (reconcile.Result, error) {
	logger := log.FromContext(ctx)

	resources, err := r.listResources(ctx)
	if err != nil {
		return reconcile.Result{}, fmt.Errorf("listing KAOS resources: %w", err)
	}
	desired := projection.Project(resources)

	serviceIDs, err := r.applyServices(ctx, desired)
	if err != nil {
		return reconcile.Result{}, err
	}
	permissionSetIDs, err := r.applyPermissionSets(ctx, desired, serviceIDs)
	if err != nil {
		return reconcile.Result{}, err
	}

	var minted, failed int
	for _, agent := range desired.Agents {
		did, agentErr := r.reconcileAgent(ctx, agent, permissionSetIDs)
		if agentErr != nil {
			failed++
			logger.Error(agentErr, "agent reconcile failed", "agent", agent.ExternalID())
			continue
		}
		if did {
			minted++
		}
	}

	if r.Prune {
		if err := r.prune(ctx, serviceIDs, permissionSetIDs, desired); err != nil {
			logger.Error(err, "prune pass failed")
		}
	}

	logger.Info("reconciled AIB projection",
		"services", len(serviceIDs), "permissionSets", len(permissionSetIDs),
		"agents", len(desired.Agents), "credentialsMinted", minted,
		"failed", failed)

	if failed > 0 {
		return reconcile.Result{}, fmt.Errorf("%d agent(s) failed to reconcile", failed)
	}
	return reconcile.Result{}, nil
}

// listResources reads every watched KAOS kind via the typed client and maps each
// object into the projection input.
func (r *AIBProjectionReconciler) listResources(ctx context.Context) ([]projection.Resource, error) {
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
			})
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
		MCPServers: a.Spec.MCPServers,
		ModelAPI:   a.Spec.ModelAPI,
	}
	if a.Spec.AgentNetwork != nil {
		res.Access = a.Spec.AgentNetwork.Access
	}
	return res
}

func (r *AIBProjectionReconciler) applyServices(ctx context.Context, desired projection.DesiredState) (map[string]string, error) {
	ids := map[string]string{}
	for _, svc := range desired.Services {
		id, err := r.AIB.CreateOrGet(ctx, "services", "client_id", svc.ClientID(), aib.ServiceBody(svc))
		if err != nil {
			return nil, fmt.Errorf("service %s: %w", svc.ClientID(), err)
		}
		ids[svc.ClientID()] = id
	}
	return ids, nil
}

func (r *AIBProjectionReconciler) applyPermissionSets(ctx context.Context, desired projection.DesiredState, serviceIDs map[string]string) (map[string]string, error) {
	ids := map[string]string{}
	for _, ps := range desired.PermissionSets {
		serviceID, ok := serviceIDs[ps.ServiceClientID()]
		if !ok {
			// Fail closed for this edge: its service could not be created.
			continue
		}
		id, err := r.AIB.CreateOrGet(ctx, "permission-sets", "name", ps.Name(), aib.PermissionSetBody(ps, serviceID))
		if err != nil {
			return nil, fmt.Errorf("permission-set %s: %w", ps.Name(), err)
		}
		ids[ps.Name()] = id
	}
	return ids, nil
}

// reconcileAgent creates the local AIB agent and mints its credential Secret if
// absent. An agent whose permission sets could not all be created is skipped
// fail-closed (no credentials are minted for an unauthorized agent). The bool
// reports whether credentials were minted on this pass.
func (r *AIBProjectionReconciler) reconcileAgent(ctx context.Context, agent projection.DesiredAgent, permissionSetIDs map[string]string) (bool, error) {
	bound := make([]string, 0, len(agent.PermissionSetNames))
	for _, name := range agent.PermissionSetNames {
		id, ok := permissionSetIDs[name]
		if !ok {
			return false, fmt.Errorf("permission set unavailable: %s", name)
		}
		bound = append(bound, id)
	}

	agentID, err := r.AIB.CreateOrGet(ctx, "agents", "display_name", agent.ExternalID(), aib.AgentBody(agent, bound))
	if err != nil {
		return false, fmt.Errorf("creating agent: %w", err)
	}

	owner := &kaosv1alpha1.Agent{}
	if err := r.Client.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: agent.Name}, owner); err != nil {
		return false, fmt.Errorf("reading agent for ownership: %w", err)
	}

	secretName := security.CredentialSecretName(r.SecretPrefix, agent.Name)
	existing := &corev1.Secret{}
	getErr := r.Client.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: secretName}, existing)
	switch {
	case getErr == nil:
		if len(existing.Data["client_id"]) > 0 {
			return false, nil // already provisioned
		}
	case !apierrors.IsNotFound(getErr):
		return false, fmt.Errorf("reading secret: %w", getErr)
	}

	cred, err := r.AIB.MintCredentials(ctx, agentID)
	if err != nil {
		return false, fmt.Errorf("minting credentials: %w", err)
	}
	if cred.ClientID == "" || cred.ClientSecret == "" {
		return false, fmt.Errorf("broker returned incomplete credentials")
	}
	if err := r.upsertSecret(ctx, owner, secretName, cred); err != nil {
		return false, fmt.Errorf("writing secret: %w", err)
	}
	return true, nil
}

func (r *AIBProjectionReconciler) upsertSecret(ctx context.Context, owner *kaosv1alpha1.Agent, name string, cred aib.Credentials) error {
	secret := &corev1.Secret{
		TypeMeta: metav1.TypeMeta{APIVersion: "v1", Kind: "Secret"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: owner.Namespace,
			Labels:    map[string]string{"app.kubernetes.io/managed-by": aibManagedBy},
		},
		Type: corev1.SecretTypeOpaque,
		StringData: map[string]string{
			"client_id":     cred.ClientID,
			"client_secret": cred.ClientSecret,
		},
	}
	// Own the Secret from its Agent so Kubernetes garbage-collects the credentials
	// when the Agent is deleted; no explicit Secret prune pass is needed.
	if err := controllerutil.SetControllerReference(owner, secret, r.Scheme); err != nil {
		return fmt.Errorf("setting owner reference: %w", err)
	}
	// Server-Side Apply: the API server reconciles create-vs-update by field
	// ownership, so there is no read-before-write or conflict branching.
	return r.Client.Patch(ctx, secret, client.Apply, client.FieldOwner(aibManagedBy), client.ForceOwnership)
}

// prune removes KAOS-managed broker records and credential Secrets that are no
// longer in the desired state, in dependency-safe order (agents, then Secrets,
// then permission sets, then services).
func (r *AIBProjectionReconciler) prune(ctx context.Context, desiredServiceIDs, desiredPermissionSetIDs map[string]string, desired projection.DesiredState) error {
	desiredAgents := map[string]bool{}
	for _, a := range desired.Agents {
		desiredAgents[a.ExternalID()] = true
	}
	agents, err := r.AIB.List(ctx, "agents")
	if err != nil {
		return err
	}
	for _, a := range agents {
		display, _ := a["display_name"].(string)
		id, _ := a["id"].(string)
		if id == "" || !projection.IsValidAgentExternalID(display) || desiredAgents[display] {
			continue
		}
		if _, err := r.AIB.Delete(ctx, "agents", id); err != nil {
			return err
		}
	}

	desiredPSNames := map[string]bool{}
	for name := range desiredPermissionSetIDs {
		desiredPSNames[name] = true
	}
	permissionSets, err := r.AIB.List(ctx, "permission-sets")
	if err != nil {
		return err
	}
	for _, ps := range permissionSets {
		name, _ := ps["name"].(string)
		id, _ := ps["id"].(string)
		if id == "" || !projection.IsKAOSPermissionSetName(name) || desiredPSNames[name] {
			continue
		}
		if _, err := r.AIB.Delete(ctx, "permission-sets", id); err != nil {
			return err
		}
	}

	desiredClientIDs := map[string]bool{}
	for clientID := range desiredServiceIDs {
		desiredClientIDs[clientID] = true
	}
	services, err := r.AIB.List(ctx, "services")
	if err != nil {
		return err
	}
	for _, svc := range services {
		clientID, _ := svc["client_id"].(string)
		id, _ := svc["id"].(string)
		if id == "" || !projection.IsKAOSServiceClientID(clientID) || desiredClientIDs[clientID] {
			continue
		}
		if _, err := r.AIB.Delete(ctx, "services", id); err != nil {
			return err
		}
	}
	return nil
}
