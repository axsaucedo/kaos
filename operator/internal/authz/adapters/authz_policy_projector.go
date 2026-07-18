package adapters

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/axsaucedo/kaos/operator/internal/authz"
	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

const authzManagedBy = "kaos-operator-authz"

// AuthzPolicyProjector applies authorization policy and grant data to a ConfigMap.
type AuthzPolicyProjector struct {
	Client             client.Client
	Name               string
	Namespace          string
	JWKSURI            string
	JWKSClient         *http.Client
	Issuer             string
	UserIssuer         string
	UserAudience       string
	UserJWKSURI        string
	StaticJWKS         map[string]any
	MapServiceAccounts bool
	MapOIDCAgents      bool
	CredentialPrefix   string
	WriteGrantData     bool
	Disabled           bool
}

// Apply renders the authorization policy and projected grant data and applies
// them to the configured ConfigMap. It is a no-op unless name and namespace are set.
func (p *AuthzPolicyProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	if p.Disabled || p.Name == "" || p.Namespace == "" {
		return nil
	}
	data := map[string]string{authz.PolicyKey: authz.Policy()}
	if p.WriteGrantData {
		grants := projection.GrantData(desired)
		issuerJWKS := map[string]any{}
		agentJWKS := p.StaticJWKS
		if p.JWKSURI != "" {
			fetched, err := authz.FetchJWKS(ctx, p.JWKSClient, p.JWKSURI)
			if err != nil {
				return err
			}
			agentJWKS = fetched
		}
		if agentJWKS != nil && security.Configured(p.Issuer) {
			issuerJWKS[p.Issuer] = agentJWKS
		}
		var agents map[string]map[string]any
		if p.MapServiceAccounts {
			agents = map[string]map[string]any{}
			for _, agent := range desired.Agents {
				agents[agent.ExternalID()] = map[string]any{
					"issuer_sub": fmt.Sprintf("system:serviceaccount:%s:%s", agent.Namespace, security.AgentServiceAccountName(agent.Name)),
					"autonomous": agent.Autonomous,
				}
			}
		}
		if p.MapOIDCAgents {
			agents = map[string]map[string]any{}
			for _, agent := range desired.Agents {
				secret := &corev1.Secret{}
				key := types.NamespacedName{Namespace: agent.Namespace, Name: security.CredentialSecretName(p.CredentialPrefix, agent.Name)}
				if err := p.Client.Get(ctx, key, secret); err != nil {
					return fmt.Errorf("reading OIDC credentials for %s: %w", agent.ExternalID(), err)
				}
				clientID := strings.TrimSpace(secretValue(secret, credentialClientIDKey))
				if clientID == "" {
					return fmt.Errorf("OIDC credentials for %s have no client_id", agent.ExternalID())
				}
				agents[agent.ExternalID()] = map[string]any{
					"issuer_azp": clientID,
					"autonomous": agent.Autonomous,
				}
			}
		}
		var userGrants map[string][]string
		var user map[string]string
		if (security.Config{UserIssuer: p.UserIssuer}).UserPlaneEnabled() {
			userKeys, err := authz.DiscoverIssuerKeys(ctx, p.JWKSClient, p.UserIssuer, p.UserJWKSURI)
			if err != nil {
				return err
			}
			if _, agentIssuer := issuerJWKS[userKeys.Issuer]; !agentIssuer {
				issuerJWKS[userKeys.Issuer] = userKeys.JWKS
			}
			userGrants = projection.UserGrantData(desired)
			user = map[string]string{"issuer": strings.TrimSpace(p.UserIssuer), "audience": strings.TrimSpace(p.UserAudience)}
		}
		dataDoc, err := authz.DataDocument(grants, userGrants, issuerJWKS, agents, user)
		if err != nil {
			return err
		}
		data[authz.DataKey] = string(dataDoc)
	}
	cm := &corev1.ConfigMap{
		TypeMeta: metav1.TypeMeta{APIVersion: "v1", Kind: "ConfigMap"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      p.Name,
			Namespace: p.Namespace,
			Labels:    map[string]string{"app.kubernetes.io/managed-by": authzManagedBy},
		},
		Data: data,
	}
	return p.Client.Patch(ctx, cm, client.Apply, client.FieldOwner(authzManagedBy), client.ForceOwnership)
}
