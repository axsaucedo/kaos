package adapters

import (
	"context"
	"fmt"
	"net/http"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
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
	StaticJWKS         map[string]any
	MapServiceAccounts bool
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
		jwks := p.StaticJWKS
		if p.JWKSURI != "" {
			fetched, err := authz.FetchJWKS(ctx, p.JWKSClient, p.JWKSURI)
			if err != nil {
				return err
			}
			jwks = fetched
		}
		var agents map[string]map[string]string
		if p.MapServiceAccounts {
			agents = map[string]map[string]string{}
			for _, agent := range desired.Agents {
				agents[agent.ExternalID()] = map[string]string{
					"issuer_sub": fmt.Sprintf("system:serviceaccount:%s:%s", agent.Namespace, security.AgentServiceAccountName(agent.Name)),
				}
			}
		}
		dataDoc, err := authz.DataDocument(grants, p.Issuer, jwks, agents)
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
