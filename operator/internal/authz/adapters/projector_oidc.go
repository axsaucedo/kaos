package adapters

import (
	"context"
	"errors"
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/authz/dcr"
	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

const (
	oidcProviderLabel             = "kaos.tools/identity-provider"
	oidcProviderLabelValue        = "oidc"
	oidcAgentExternalIDAnnotation = "kaos.tools/agent-external-id"
	oidcAgentFinalizer            = "kaos.tools/oidc-client-finalizer"
	registrationClientURIKey      = "registration_client_uri"
	registrationAccessTokenKey    = "registration_access_token"
	credentialClientIDKey         = "client_id"
	credentialClientSecretKey     = "client_secret"
)

// DCRClient is the RFC 7591/7592 subset needed by OIDCProjector.
type DCRClient interface {
	Register(context.Context, dcr.RegistrationRequest) (dcr.Registration, error)
	Get(context.Context, dcr.Reference) (dcr.Registration, error)
	Delete(context.Context, dcr.Reference) error
}

// OIDCProjector provisions one OAuth client and credential Secret per agent.
type OIDCProjector struct {
	Client       client.Client
	Scheme       *runtime.Scheme
	DCR          DCRClient
	SecretPrefix string
	Prune        bool
	Namespaces   []string
}

// Apply reconciles the complete projected agent set.
func (p *OIDCProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	logger := log.FromContext(ctx)
	var reconcileErrors []error
	var registered int
	for _, agent := range desired.Agents {
		created, err := p.reconcileAgent(ctx, agent)
		if err != nil {
			logger.Error(err, "OIDC client reconcile failed", "agent", agent.ExternalID())
			reconcileErrors = append(reconcileErrors, fmt.Errorf("reconciling %s: %w", agent.ExternalID(), err))
			continue
		}
		if created {
			registered++
		}
	}
	if p.Prune {
		if err := p.prune(ctx, desired); err != nil {
			logger.Error(err, "OIDC client prune failed")
			reconcileErrors = append(reconcileErrors, err)
		}
	}
	logger.Info("reconciled OIDC identity projection", "agents", len(desired.Agents), "clientsRegistered", registered, "failed", len(reconcileErrors))
	return errors.Join(reconcileErrors...)
}

func (p *OIDCProjector) reconcileAgent(ctx context.Context, agent projection.DesiredAgent) (bool, error) {
	owner := &kaosv1alpha1.Agent{}
	key := types.NamespacedName{Namespace: agent.Namespace, Name: agent.Name}
	if err := p.Client.Get(ctx, key, owner); err != nil {
		return false, fmt.Errorf("reading agent for ownership: %w", err)
	}
	if owner.DeletionTimestamp != nil {
		return false, p.finalizeAgent(ctx, owner)
	}
	if !controllerutil.ContainsFinalizer(owner, oidcAgentFinalizer) {
		before := owner.DeepCopy()
		controllerutil.AddFinalizer(owner, oidcAgentFinalizer)
		if err := p.Client.Patch(ctx, owner, client.MergeFrom(before)); err != nil {
			return false, fmt.Errorf("adding OIDC client finalizer: %w", err)
		}
	}

	secretName := security.CredentialSecretName(p.SecretPrefix, agent.Name)
	secret := &corev1.Secret{}
	err := p.Client.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: secretName}, secret)
	switch {
	case err == nil:
		ref := registrationReference(secret)
		if completeReference(ref) {
			registration, getErr := p.DCR.Get(ctx, ref)
			switch {
			case getErr == nil:
				if registration.ClientID != "" && registration.ClientID != ref.ClientID {
					return false, fmt.Errorf("provider returned client_id %q for stored client_id %q", registration.ClientID, ref.ClientID)
				}
				if secretValue(secret, credentialClientSecretKey) == "" {
					return false, fmt.Errorf("credential Secret has no client_secret for existing OAuth client")
				}
				return false, nil
			case dcr.IsNotFound(getErr):
				// The provider no longer has the client. Re-register below and
				// atomically replace the stale local registration reference.
			default:
				return false, fmt.Errorf("checking existing OAuth client: %w", getErr)
			}
		} else if secretValue(secret, credentialClientIDKey) != "" || secretValue(secret, credentialClientSecretKey) != "" {
			return false, fmt.Errorf("credential Secret has an incomplete registration reference")
		}
	case apierrors.IsNotFound(err):
	case err != nil:
		return false, fmt.Errorf("reading credential Secret: %w", err)
	}

	registration, err := p.DCR.Register(ctx, dcr.AgentRegistrationRequest(agent.ExternalID()))
	if err != nil {
		return false, err
	}
	ref := dcr.Reference{
		ClientID: registration.ClientID, RegistrationClientURI: registration.RegistrationClientURI,
		RegistrationAccessToken: registration.RegistrationAccessToken,
	}
	if err := p.upsertSecret(ctx, owner, secretName, agent.ExternalID(), registration); err != nil {
		cleanupErr := p.DCR.Delete(ctx, ref)
		return false, errors.Join(fmt.Errorf("writing credential Secret: %w", err), cleanupErr)
	}
	return true, nil
}

func (p *OIDCProjector) finalizeAgent(ctx context.Context, owner *kaosv1alpha1.Agent) error {
	if !controllerutil.ContainsFinalizer(owner, oidcAgentFinalizer) {
		return nil
	}
	secretName := security.CredentialSecretName(p.SecretPrefix, owner.Name)
	secret := &corev1.Secret{}
	err := p.Client.Get(ctx, types.NamespacedName{Namespace: owner.Namespace, Name: secretName}, secret)
	if err == nil {
		ref := registrationReference(secret)
		if !completeReference(ref) {
			return fmt.Errorf("credential Secret has an incomplete registration reference")
		}
		if err := p.DCR.Delete(ctx, ref); err != nil {
			return fmt.Errorf("deleting OAuth client for %s: %w", projection.AgentExternalID(owner.Namespace, owner.Name), err)
		}
		if err := p.Client.Delete(ctx, secret); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("deleting Secret %s/%s: %w", secret.Namespace, secret.Name, err)
		}
	} else if !apierrors.IsNotFound(err) {
		return fmt.Errorf("reading credential Secret during finalization: %w", err)
	}
	return p.removeAgentFinalizer(ctx, owner)
}

func (p *OIDCProjector) removeAgentFinalizer(ctx context.Context, owner *kaosv1alpha1.Agent) error {
	if !controllerutil.ContainsFinalizer(owner, oidcAgentFinalizer) {
		return nil
	}
	before := owner.DeepCopy()
	controllerutil.RemoveFinalizer(owner, oidcAgentFinalizer)
	if err := p.Client.Patch(ctx, owner, client.MergeFrom(before)); err != nil {
		return fmt.Errorf("removing OIDC client finalizer: %w", err)
	}
	return nil
}

func (p *OIDCProjector) removeSecretOwnerFinalizer(ctx context.Context, secret *corev1.Secret) error {
	for _, ownerRef := range secret.OwnerReferences {
		if ownerRef.Kind != "Agent" || ownerRef.Name == "" {
			continue
		}
		owner := &kaosv1alpha1.Agent{}
		err := p.Client.Get(ctx, types.NamespacedName{Namespace: secret.Namespace, Name: ownerRef.Name}, owner)
		if apierrors.IsNotFound(err) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("reading Agent %s/%s during prune: %w", secret.Namespace, ownerRef.Name, err)
		}
		return p.removeAgentFinalizer(ctx, owner)
	}
	return nil
}

func (p *OIDCProjector) upsertSecret(ctx context.Context, owner *kaosv1alpha1.Agent, name, externalID string, registration dcr.Registration) error {
	secret := &corev1.Secret{
		TypeMeta: metav1.TypeMeta{APIVersion: "v1", Kind: "Secret"},
		ObjectMeta: metav1.ObjectMeta{
			Name: name, Namespace: owner.Namespace,
			Labels: map[string]string{
				"app.kubernetes.io/managed-by": authzManagedBy,
				oidcProviderLabel:              oidcProviderLabelValue,
			},
			Annotations: map[string]string{oidcAgentExternalIDAnnotation: externalID},
		},
		Type: corev1.SecretTypeOpaque,
		StringData: map[string]string{
			credentialClientIDKey:      registration.ClientID,
			credentialClientSecretKey:  registration.ClientSecret,
			registrationClientURIKey:   registration.RegistrationClientURI,
			registrationAccessTokenKey: registration.RegistrationAccessToken,
		},
	}
	if err := controllerutil.SetControllerReference(owner, secret, p.Scheme); err != nil {
		return fmt.Errorf("setting owner reference: %w", err)
	}
	return p.Client.Patch(ctx, secret, client.Apply, client.FieldOwner(authzManagedBy), client.ForceOwnership)
}

func (p *OIDCProjector) prune(ctx context.Context, desired projection.DesiredState) error {
	desiredAgents := make(map[string]bool, len(desired.Agents))
	for _, agent := range desired.Agents {
		desiredAgents[agent.ExternalID()] = true
	}
	var pruneErrors []error
	for _, namespace := range projectionNamespaces(p.Namespaces) {
		secrets := &corev1.SecretList{}
		options := []client.ListOption{client.MatchingLabels{
			"app.kubernetes.io/managed-by": authzManagedBy,
			oidcProviderLabel:              oidcProviderLabelValue,
		}}
		if namespace != "" {
			options = append(options, client.InNamespace(namespace))
		}
		if err := p.Client.List(ctx, secrets, options...); err != nil {
			pruneErrors = append(pruneErrors, fmt.Errorf("listing OIDC credential Secrets: %w", err))
			continue
		}
		for i := range secrets.Items {
			secret := &secrets.Items[i]
			externalID := strings.TrimSpace(secret.Annotations[oidcAgentExternalIDAnnotation])
			if externalID == "" || desiredAgents[externalID] {
				continue
			}
			ref := registrationReference(secret)
			if !completeReference(ref) {
				pruneErrors = append(pruneErrors, fmt.Errorf("Secret %s/%s has an incomplete registration reference", secret.Namespace, secret.Name))
				continue
			}
			if err := p.DCR.Delete(ctx, ref); err != nil {
				pruneErrors = append(pruneErrors, fmt.Errorf("deleting OAuth client for %s: %w", externalID, err))
				continue
			}
			if err := p.removeSecretOwnerFinalizer(ctx, secret); err != nil {
				pruneErrors = append(pruneErrors, err)
				continue
			}
			if err := p.Client.Delete(ctx, secret); err != nil && !apierrors.IsNotFound(err) {
				pruneErrors = append(pruneErrors, fmt.Errorf("deleting Secret %s/%s: %w", secret.Namespace, secret.Name, err))
			}
		}
	}
	return errors.Join(pruneErrors...)
}

func projectionNamespaces(configured []string) []string {
	if len(configured) == 0 {
		return []string{""}
	}
	return configured
}

func registrationReference(secret *corev1.Secret) dcr.Reference {
	return dcr.Reference{
		ClientID:                secretValue(secret, credentialClientIDKey),
		RegistrationClientURI:   secretValue(secret, registrationClientURIKey),
		RegistrationAccessToken: secretValue(secret, registrationAccessTokenKey),
	}
}

func completeReference(ref dcr.Reference) bool {
	return strings.TrimSpace(ref.ClientID) != "" && strings.TrimSpace(ref.RegistrationClientURI) != "" && strings.TrimSpace(ref.RegistrationAccessToken) != ""
}

func secretValue(secret *corev1.Secret, key string) string {
	if value := secret.Data[key]; len(value) > 0 {
		return string(value)
	}
	return secret.StringData[key]
}
