package adapters

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/aib"
	"github.com/axsaucedo/kaos/operator/internal/authz"
	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

// AgentBody is the identity-broker admin registration payload for an agent.
func AgentBody(a projection.DesiredAgent) map[string]any {
	return map[string]any{
		"display_name": a.ExternalID(),
		"description":  fmt.Sprintf("KAOS agent %s/%s", a.Namespace, a.Name),
	}
}

// AIBAdmin is the subset of the broker admin client the projector needs.
type AIBAdmin interface {
	ListAgents(ctx context.Context) ([]map[string]any, error)
	CreateOrGetAgent(ctx context.Context, externalID string, body map[string]any) (string, error)
	DeleteAgent(ctx context.Context, id string) (bool, error)
	MintCredentials(ctx context.Context, agentID string) (aib.Credentials, error)
}

// BrokerProjector provisions agent identities and credentials in the broker.
type BrokerProjector struct {
	Client       client.Client
	Scheme       *runtime.Scheme
	AIB          AIBAdmin
	SecretPrefix string
	Prune        bool
	HTTPClient   *http.Client
	Issuer       string
	Namespaces   []string
}

// Apply registers agents and delivers their credentials through Secrets.
func (p *BrokerProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	logger := log.FromContext(ctx)
	if err := p.updateIssuerConditions(ctx); err != nil {
		logger.Error(err, "unable to update AIB issuer consistency conditions")
	}
	var minted, failed int
	for _, agent := range desired.Agents {
		did, agentErr := p.reconcileAgent(ctx, agent)
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
		if err := p.pruneAgents(ctx, desired); err != nil {
			logger.Error(err, "prune pass failed")
		}
	}

	logger.Info("reconciled broker identity projection",
		"agents", len(desired.Agents), "credentialsMinted", minted,
		"failed", failed)

	if failed > 0 {
		return fmt.Errorf("%d agent(s) failed to reconcile", failed)
	}
	return nil
}

const identityIssuerDegradedCondition = "IdentityIssuerDegraded"

func (p *BrokerProjector) updateIssuerConditions(ctx context.Context) error {
	configured := strings.TrimSpace(p.Issuer)
	if configured == "" {
		return nil
	}
	discovered, checkErr := authz.DiscoverIssuer(ctx, p.HTTPClient, configured)
	condition := metav1.Condition{
		Type:    identityIssuerDegradedCondition,
		Status:  metav1.ConditionFalse,
		Reason:  "IssuerConsistent",
		Message: fmt.Sprintf("Configured issuer %q matches AIB discovery", configured),
	}
	if checkErr != nil {
		condition.Status = metav1.ConditionTrue
		condition.Reason = "IssuerDiscoveryFailed"
		condition.Message = checkErr.Error()
		log.FromContext(ctx).Error(checkErr, "unable to verify AIB issuer consistency", "configuredIssuer", configured)
	} else if discovered != configured {
		condition.Status = metav1.ConditionTrue
		condition.Reason = "IssuerMismatch"
		condition.Message = fmt.Sprintf("Configured issuer %q does not match AIB discovery issuer %q", configured, discovered)
		log.FromContext(ctx).Error(fmt.Errorf("%s", condition.Message), "AIB issuer mismatch", "configuredIssuer", configured, "discoveredIssuer", discovered)
	}

	namespaces := p.Namespaces
	if len(namespaces) == 0 {
		namespaces = []string{""}
	}
	for _, namespace := range namespaces {
		agents := &kaosv1alpha1.AgentList{}
		var options []client.ListOption
		if namespace != "" {
			options = append(options, client.InNamespace(namespace))
		}
		if err := p.Client.List(ctx, agents, options...); err != nil {
			return fmt.Errorf("listing Agents for issuer condition: %w", err)
		}
		for i := range agents.Items {
			agent := &agents.Items[i]
			original := agent.DeepCopy()
			condition.ObservedGeneration = agent.Generation
			if !meta.SetStatusCondition(&agent.Status.Conditions, condition) {
				continue
			}
			if err := p.Client.Status().Patch(ctx, agent, client.MergeFrom(original)); err != nil {
				return fmt.Errorf("updating Agent %s/%s issuer condition: %w", agent.Namespace, agent.Name, err)
			}
		}
	}
	return nil
}

func (p *BrokerProjector) reconcileAgent(ctx context.Context, agent projection.DesiredAgent) (bool, error) {
	agentID, err := p.AIB.CreateOrGetAgent(ctx, agent.ExternalID(), AgentBody(agent))
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

func (p *BrokerProjector) pruneAgents(ctx context.Context, desired projection.DesiredState) error {
	desiredAgents := map[string]bool{}
	for _, a := range desired.Agents {
		desiredAgents[a.ExternalID()] = true
	}
	agents, err := p.AIB.ListAgents(ctx)
	if err != nil {
		return err
	}
	for _, a := range agents {
		display, _ := a["display_name"].(string)
		id, _ := a["id"].(string)
		if id == "" || !projection.IsValidAgentExternalID(display) || desiredAgents[display] {
			continue
		}
		if _, err := p.AIB.DeleteAgent(ctx, id); err != nil {
			return err
		}
	}
	return nil
}
