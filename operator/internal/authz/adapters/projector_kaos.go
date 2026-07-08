package adapters

import (
	"context"
	"net/http"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/axsaucedo/kaos/operator/internal/authz"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

const authzManagedBy = "kaos-operator-authz"

// ConfigMapProjector applies authorization policy and grant data to a ConfigMap.
type ConfigMapProjector struct {
	Client     client.Client
	Name       string
	Namespace  string
	JWKSURI    string
	JWKSClient *http.Client
}

// Apply renders the authorization policy and projected grant data and applies
// them to the configured ConfigMap. It is a no-op unless name and namespace are set.
func (p *ConfigMapProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	if p.Name == "" || p.Namespace == "" {
		return nil
	}
	grants := projection.GrantData(desired)
	var jwks map[string]any
	if p.JWKSURI != "" {
		fetched, err := authz.FetchJWKS(ctx, p.JWKSClient, p.JWKSURI)
		if err != nil {
			return err
		}
		jwks = fetched
	}
	data, err := authz.ConfigMapData(grants, jwks)
	if err != nil {
		return err
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
