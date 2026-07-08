package adapters

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/aib"
	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

// ServiceBody is the identity-broker admin create payload for a synthetic service projected from an edge target.
func ServiceBody(s projection.DesiredService) map[string]any {
	path := logicalPath(s.Namespace, s.Name)
	return map[string]any{
		"display_name":  fmt.Sprintf("KAOS %s %s (synthetic)", s.Kind.DisplayLabel, path),
		"client_id":     s.ClientID(),
		"client_secret": "synthetic",
		"issuer_uri":    fmt.Sprintf("https://kaos.local/%s/%s", s.Kind.Slug, path),
		"discovery":     map[string]any{"enable_discovery": false},
		"endpoints": map[string]any{
			"token_endpoint":     "https://kaos.local/t",
			"authorize_endpoint": "https://kaos.local/a",
		},
		"scopes": []any{map[string]any{"scope_value": projection.CallScope, "description": s.Kind.ScopeDescription}},
	}
}

// PermissionSetBody is the identity-broker admin create payload for a permission set granting "call" on one synthetic service.
func PermissionSetBody(p projection.DesiredPermissionSet, serviceID string) map[string]any {
	return map[string]any{
		"name":        p.Name(),
		"description": fmt.Sprintf("call %s/%s", p.Namespace, p.Target),
		"service_scopes": []any{map[string]any{
			"service_id":       serviceID,
			"scopes":           []any{projection.CallScope},
			"requirement_type": "mandatory",
		}},
	}
}

// AgentBody is the identity-broker admin create payload binding an agent to its permission sets.
func AgentBody(a projection.DesiredAgent, permissionSetIDs []string) map[string]any {
	bindings := make([]any, 0, len(permissionSetIDs))
	for _, pid := range permissionSetIDs {
		bindings = append(bindings, map[string]any{"permission_set_id": pid, "requirement_type": "mandatory"})
	}
	return map[string]any{
		"display_name":    a.ExternalID(),
		"description":     fmt.Sprintf("KAOS agent %s/%s", a.Namespace, a.Name),
		"permission_sets": bindings,
	}
}

func logicalPath(namespace, name string) string {
	return namespace + "/" + name
}

// AIBAdmin is the subset of the broker admin client the projector needs.
type AIBAdmin interface {
	List(ctx context.Context, collection string) ([]map[string]any, error)
	CreateOrGet(ctx context.Context, collection, matchField, matchValue string, body map[string]any) (string, error)
	Delete(ctx context.Context, collection, id string) (bool, error)
	MintCredentials(ctx context.Context, agentID string) (aib.Credentials, error)
}

// BrokerProjector applies authorization state to the identity broker.
type BrokerProjector struct {
	Client       client.Client
	Scheme       *runtime.Scheme
	AIB          AIBAdmin
	SecretPrefix string
	Prune        bool
}

// Apply registers services, permission sets, agents and credential Secrets.
func (p *BrokerProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	logger := log.FromContext(ctx)
	serviceIDs, err := p.applyServices(ctx, desired)
	if err != nil {
		return err
	}
	permissionSetIDs, err := p.applyPermissionSets(ctx, desired, serviceIDs)
	if err != nil {
		return err
	}

	var minted, failed int
	for _, agent := range desired.Agents {
		did, agentErr := p.reconcileAgent(ctx, agent, permissionSetIDs)
		if agentErr != nil {
			failed++
			logger.Error(agentErr, "agent reconcile failed", "agent", agent.ExternalID())
			continue
		}
		if did {
			minted++
		}
	}

	if p.Prune {
		if err := p.prune(ctx, serviceIDs, permissionSetIDs, desired); err != nil {
			logger.Error(err, "prune pass failed")
		}
	}

	logger.Info("reconciled authorization projection",
		"services", len(serviceIDs), "permissionSets", len(permissionSetIDs),
		"agents", len(desired.Agents), "credentialsMinted", minted,
		"failed", failed)

	if failed > 0 {
		return fmt.Errorf("%d agent(s) failed to reconcile", failed)
	}
	return nil
}

func (p *BrokerProjector) applyServices(ctx context.Context, desired projection.DesiredState) (map[string]string, error) {
	ids := map[string]string{}
	for _, svc := range desired.Services {
		id, err := p.AIB.CreateOrGet(ctx, "services", "client_id", svc.ClientID(), ServiceBody(svc))
		if err != nil {
			return nil, fmt.Errorf("service %s: %w", svc.ClientID(), err)
		}
		ids[svc.ClientID()] = id
	}
	return ids, nil
}

func (p *BrokerProjector) applyPermissionSets(ctx context.Context, desired projection.DesiredState, serviceIDs map[string]string) (map[string]string, error) {
	ids := map[string]string{}
	for _, ps := range desired.PermissionSets {
		serviceID, ok := serviceIDs[ps.ServiceClientID()]
		if !ok {
			continue
		}
		id, err := p.AIB.CreateOrGet(ctx, "permission-sets", "name", ps.Name(), PermissionSetBody(ps, serviceID))
		if err != nil {
			return nil, fmt.Errorf("permission-set %s: %w", ps.Name(), err)
		}
		ids[ps.Name()] = id
	}
	return ids, nil
}

func (p *BrokerProjector) reconcileAgent(ctx context.Context, agent projection.DesiredAgent, permissionSetIDs map[string]string) (bool, error) {
	bound := make([]string, 0, len(agent.PermissionSetNames))
	for _, name := range agent.PermissionSetNames {
		id, ok := permissionSetIDs[name]
		if !ok {
			return false, fmt.Errorf("permission set unavailable: %s", name)
		}
		bound = append(bound, id)
	}

	agentID, err := p.AIB.CreateOrGet(ctx, "agents", "display_name", agent.ExternalID(), AgentBody(agent, bound))
	if err != nil {
		return false, fmt.Errorf("creating agent: %w", err)
	}

	owner := &kaosv1alpha1.Agent{}
	if err := p.Client.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: agent.Name}, owner); err != nil {
		return false, fmt.Errorf("reading agent for ownership: %w", err)
	}

	secretName := security.CredentialSecretName(p.SecretPrefix, agent.Name)
	existing := &corev1.Secret{}
	getErr := p.Client.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: secretName}, existing)
	switch {
	case getErr == nil:
		if len(existing.Data["client_id"]) > 0 {
			return false, nil
		}
	case !apierrors.IsNotFound(getErr):
		return false, fmt.Errorf("reading secret: %w", getErr)
	}

	cred, err := p.AIB.MintCredentials(ctx, agentID)
	if err != nil {
		return false, fmt.Errorf("minting credentials: %w", err)
	}
	if cred.ClientID == "" || cred.ClientSecret == "" {
		return false, fmt.Errorf("broker returned incomplete credentials")
	}
	if err := p.upsertSecret(ctx, owner, secretName, cred); err != nil {
		return false, fmt.Errorf("writing secret: %w", err)
	}
	return true, nil
}

func (p *BrokerProjector) upsertSecret(ctx context.Context, owner *kaosv1alpha1.Agent, name string, cred aib.Credentials) error {
	secret := &corev1.Secret{
		TypeMeta: metav1.TypeMeta{APIVersion: "v1", Kind: "Secret"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: owner.Namespace,
			Labels:    map[string]string{"app.kubernetes.io/managed-by": authzManagedBy},
		},
		Type: corev1.SecretTypeOpaque,
		StringData: map[string]string{
			"client_id":     cred.ClientID,
			"client_secret": cred.ClientSecret,
		},
	}
	if err := controllerutil.SetControllerReference(owner, secret, p.Scheme); err != nil {
		return fmt.Errorf("setting owner reference: %w", err)
	}
	return p.Client.Patch(ctx, secret, client.Apply, client.FieldOwner(authzManagedBy), client.ForceOwnership)
}

func (p *BrokerProjector) prune(ctx context.Context, desiredServiceIDs, desiredPermissionSetIDs map[string]string, desired projection.DesiredState) error {
	desiredAgents := map[string]bool{}
	for _, a := range desired.Agents {
		desiredAgents[a.ExternalID()] = true
	}
	agents, err := p.AIB.List(ctx, "agents")
	if err != nil {
		return err
	}
	for _, a := range agents {
		display, _ := a["display_name"].(string)
		id, _ := a["id"].(string)
		if id == "" || !projection.IsValidAgentExternalID(display) || desiredAgents[display] {
			continue
		}
		if _, err := p.AIB.Delete(ctx, "agents", id); err != nil {
			return err
		}
	}

	desiredPSNames := map[string]bool{}
	for name := range desiredPermissionSetIDs {
		desiredPSNames[name] = true
	}
	permissionSets, err := p.AIB.List(ctx, "permission-sets")
	if err != nil {
		return err
	}
	for _, ps := range permissionSets {
		name, _ := ps["name"].(string)
		id, _ := ps["id"].(string)
		if id == "" || !projection.IsKAOSPermissionSetName(name) || desiredPSNames[name] {
			continue
		}
		if _, err := p.AIB.Delete(ctx, "permission-sets", id); err != nil {
			return err
		}
	}

	desiredClientIDs := map[string]bool{}
	for clientID := range desiredServiceIDs {
		desiredClientIDs[clientID] = true
	}
	services, err := p.AIB.List(ctx, "services")
	if err != nil {
		return err
	}
	for _, svc := range services {
		clientID, _ := svc["client_id"].(string)
		id, _ := svc["id"].(string)
		if id == "" || !projection.IsKAOSServiceClientID(clientID) || desiredClientIDs[clientID] {
			continue
		}
		if _, err := p.AIB.Delete(ctx, "services", id); err != nil {
			return err
		}
	}
	return nil
}
