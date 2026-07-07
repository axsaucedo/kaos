// Package sync contains the controller-runtime reconciler that projects KAOS
// resources into AIB and provisions per-agent credential Secrets.
//
// Unlike a per-object controller, the projection is a whole-world function
// (agents reference other resources, and identity-collision resolution needs
// every resource of a kind). So the controller watches all three KAOS kinds but
// funnels every change to a single sentinel reconcile.Request: the workqueue
// then naturally coalesces a burst of changes into one full reconcile, and
// controller-runtime supplies the watch, cache, leader election, periodic
// resync and requeue-on-error for free.
package sync

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"github.com/axsaucedo/kaos/sync-service/internal/aib"
	"github.com/axsaucedo/kaos/sync-service/internal/projection"
)

const (
	kaosGroup   = "kaos.tools"
	kaosVersion = "v1alpha1"
	managedBy   = "kaos-sync"
)

// kaosKinds maps each watched CRD kind to its list kind.
var kaosKinds = []struct {
	kind, listKind string
}{
	{"Agent", "AgentList"},
	{"MCPServer", "MCPServerList"},
	{"ModelAPI", "ModelAPIList"},
}

// sentinel is the single request key every change maps to.
var sentinel = reconcile.Request{NamespacedName: types.NamespacedName{Namespace: "_kaos", Name: "_sync"}}

// AIBAdmin is the subset of the AIB admin client the reconciler needs (an
// interface so the reconciler can be unit tested with a fake). It is satisfied
// directly by *aib.Client.
type AIBAdmin interface {
	List(ctx context.Context, collection string) ([]map[string]any, error)
	CreateOrGet(ctx context.Context, collection, matchField, matchValue string, body map[string]any) (string, error)
	Delete(ctx context.Context, collection, id string) (bool, error)
	MintCredentials(ctx context.Context, agentID string) (aib.Credentials, error)
}

// Reconciler projects KAOS resources into AIB and mints credential Secrets.
type Reconciler struct {
	Client       client.Client
	AIB          AIBAdmin
	Namespaces   []string
	SecretPrefix string
	Prune        bool
}

// CredentialSecretName is the per-agent credential Secret name, derivable by
// both the sync service and the operator.
func CredentialSecretName(prefix, agentName string) string {
	return prefix + "-" + agentName
}

// SetupWithManager registers the controller, watching all three KAOS kinds and
// funnelling every event to the sentinel request.
func (r *Reconciler) SetupWithManager(mgr ctrl.Manager) error {
	toSentinel := handler.EnqueueRequestsFromMapFunc(func(context.Context, client.Object) []reconcile.Request {
		return []reconcile.Request{sentinel}
	})
	b := builder.ControllerManagedBy(mgr).Named("kaos-sync")
	for _, k := range kaosKinds {
		u := &unstructured.Unstructured{}
		u.SetGroupVersionKind(schema.GroupVersionKind{Group: kaosGroup, Version: kaosVersion, Kind: k.kind})
		b = b.Watches(u, toSentinel)
	}
	return b.Complete(r)
}

// Reconcile runs a full projection pass: list every KAOS resource, project the
// desired AIB state, apply it, and provision credential Secrets. Returning an
// error requeues the sentinel with backoff, so transient broker failures retry.
func (r *Reconciler) Reconcile(ctx context.Context, _ reconcile.Request) (reconcile.Result, error) {
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

	logger.Info("reconciled",
		"services", len(serviceIDs), "permissionSets", len(permissionSetIDs),
		"agents", len(desired.Agents), "credentialsMinted", minted,
		"failed", failed)

	if failed > 0 {
		return reconcile.Result{}, fmt.Errorf("%d agent(s) failed to reconcile", failed)
	}
	return reconcile.Result{}, nil
}

func (r *Reconciler) listResources(ctx context.Context) ([]projection.Resource, error) {
	namespaces := r.Namespaces
	if len(namespaces) == 0 {
		namespaces = []string{""} // cluster-wide
	}
	var out []projection.Resource
	for _, k := range kaosKinds {
		for _, ns := range namespaces {
			list := &unstructured.UnstructuredList{}
			list.SetGroupVersionKind(schema.GroupVersionKind{Group: kaosGroup, Version: kaosVersion, Kind: k.listKind})
			opts := []client.ListOption{}
			if ns != "" {
				opts = append(opts, client.InNamespace(ns))
			}
			if err := r.Client.List(ctx, list, opts...); err != nil {
				return nil, err
			}
			for i := range list.Items {
				out = append(out, toResource(k.kind, &list.Items[i]))
			}
		}
	}
	return out, nil
}

// toResource extracts the projection-relevant fields from an unstructured CRD.
func toResource(kind string, obj *unstructured.Unstructured) projection.Resource {
	res := projection.Resource{
		Kind:      kind,
		Namespace: obj.GetNamespace(),
		Name:      obj.GetName(),
	}
	if kind == projection.AgentKind {
		if mcps, ok, _ := unstructured.NestedStringSlice(obj.Object, "spec", "mcpServers"); ok {
			res.MCPServers = mcps
		}
		if modelAPI, ok, _ := unstructured.NestedString(obj.Object, "spec", "modelAPI"); ok {
			res.ModelAPI = modelAPI
		}
		if access, ok, _ := unstructured.NestedStringSlice(obj.Object, "spec", "agentNetwork", "access"); ok {
			res.Access = access
		}
	}
	return res
}

func (r *Reconciler) applyServices(ctx context.Context, desired projection.DesiredState) (map[string]string, error) {
	ids := map[string]string{}
	for _, svc := range desired.Services {
		id, err := r.AIB.CreateOrGet(ctx, "services", "client_id", svc.ClientID(), svc.AdminBody())
		if err != nil {
			return nil, fmt.Errorf("service %s: %w", svc.ClientID(), err)
		}
		ids[svc.ClientID()] = id
	}
	return ids, nil
}

func (r *Reconciler) applyPermissionSets(ctx context.Context, desired projection.DesiredState, serviceIDs map[string]string) (map[string]string, error) {
	ids := map[string]string{}
	for _, ps := range desired.PermissionSets {
		serviceID, ok := serviceIDs[ps.ServiceClientID()]
		if !ok {
			// Fail closed for this edge: its service could not be created.
			continue
		}
		id, err := r.AIB.CreateOrGet(ctx, "permission-sets", "name", ps.Name(), ps.AdminBody(serviceID))
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
func (r *Reconciler) reconcileAgent(ctx context.Context, agent projection.DesiredAgent, permissionSetIDs map[string]string) (bool, error) {
	bound := make([]string, 0, len(agent.PermissionSetNames))
	for _, name := range agent.PermissionSetNames {
		id, ok := permissionSetIDs[name]
		if !ok {
			return false, fmt.Errorf("permission set unavailable: %s", name)
		}
		bound = append(bound, id)
	}

	agentID, err := r.AIB.CreateOrGet(ctx, "agents", "display_name", agent.ExternalID(), agent.AdminBody(bound))
	if err != nil {
		return false, fmt.Errorf("creating agent: %w", err)
	}

	secretName := CredentialSecretName(r.SecretPrefix, agent.Name)
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
	if err := r.upsertSecret(ctx, agent.Namespace, secretName, cred); err != nil {
		return false, fmt.Errorf("writing secret: %w", err)
	}
	return true, nil
}

func (r *Reconciler) upsertSecret(ctx context.Context, namespace, name string, cred aib.Credentials) error {
	secret := &corev1.Secret{
		TypeMeta: metav1.TypeMeta{APIVersion: "v1", Kind: "Secret"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels:    map[string]string{"app.kubernetes.io/managed-by": managedBy},
		},
		Type: corev1.SecretTypeOpaque,
		StringData: map[string]string{
			"client_id":     cred.ClientID,
			"client_secret": cred.ClientSecret,
		},
	}
	// Server-Side Apply: the API server reconciles create-vs-update by field
	// ownership, so there is no read-before-write or conflict branching.
	return r.Client.Patch(ctx, secret, client.Apply, client.FieldOwner(managedBy), client.ForceOwnership)
}

// prune removes KAOS-managed broker records and credential Secrets that are no
// longer in the desired state, in dependency-safe order (agents, then Secrets,
// then permission sets, then services).
func (r *Reconciler) prune(ctx context.Context, desiredServiceIDs, desiredPermissionSetIDs map[string]string, desired projection.DesiredState) error {
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

	if err := r.pruneSecrets(ctx, desired); err != nil {
		return err
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

func (r *Reconciler) pruneSecrets(ctx context.Context, desired projection.DesiredState) error {
	desiredSecrets := map[string]bool{}
	for _, a := range desired.Agents {
		desiredSecrets[a.Namespace+"/"+CredentialSecretName(r.SecretPrefix, a.Name)] = true
	}
	list := &corev1.SecretList{}
	if err := r.Client.List(ctx, list, client.MatchingLabels{"app.kubernetes.io/managed-by": managedBy}); err != nil {
		return err
	}
	for i := range list.Items {
		s := &list.Items[i]
		if desiredSecrets[s.Namespace+"/"+s.Name] {
			continue
		}
		if err := r.Client.Delete(ctx, s); err != nil && !apierrors.IsNotFound(err) {
			return err
		}
	}
	return nil
}
