package adapters

import (
	"context"
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

// AIBExchangeAdmin is the AIB admin API subset used only for token exchange.
type AIBExchangeAdmin interface {
	Upsert(context.Context, string, string, string, map[string]any) (string, error)
}

// ExchangeProjector projects real third-party services, permission sets, and agents.
// It is deliberately separate from identity and the data.kaos.* PDP projection.
type ExchangeProjector struct {
	Client           client.Client
	AIB              AIBExchangeAdmin
	Enabled          bool
	OIDCSecretPrefix string
}

// Apply reconciles exchange declarations when the feature gate is enabled.
func (p *ExchangeProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	if !p.Enabled {
		return nil
	}
	type agentPlan struct {
		namespace        string
		name             string
		clientID         string
		permissionSetIDs []string
	}
	agents := map[string]*agentPlan{}
	for _, service := range desired.ThirdPartyServices {
		bindings, err := p.applyService(ctx, service)
		if err != nil {
			return fmt.Errorf("projecting ThirdPartyService %s/%s: %w", service.Namespace, service.Name, err)
		}
		for agent, permissionSetID := range bindings {
			key := service.Namespace + "/" + agent
			plan := agents[key]
			if plan == nil {
				clientID, err := p.agentClientID(ctx, service.Namespace, agent)
				if err != nil {
					return err
				}
				plan = &agentPlan{namespace: service.Namespace, name: agent, clientID: clientID}
				agents[key] = plan
			}
			plan.permissionSetIDs = append(plan.permissionSetIDs, permissionSetID)
		}
	}
	for _, agent := range agents {
		externalID := projection.AgentExternalID(agent.namespace, agent.name)
		if _, err := p.AIB.Upsert(ctx, "agents", "external_id", externalID, exchangeAgentBody(agent.namespace, agent.name, agent.clientID, agent.permissionSetIDs)); err != nil {
			return fmt.Errorf("registering exchange agent %q: %w", agent.name, err)
		}
	}
	return nil
}

func (p *ExchangeProjector) applyService(ctx context.Context, service projection.DesiredThirdPartyService) (map[string]string, error) {
	secret, err := p.readSecret(ctx, service.Namespace, service.ClientSecretName)
	if err != nil {
		return nil, fmt.Errorf("reading OAuth client Secret: %w", err)
	}
	clientSecret := secretValue(secret, service.ClientSecretKey)
	if clientSecret == "" {
		return nil, fmt.Errorf("OAuth client Secret %s/%s has no %q key", service.Namespace, service.ClientSecretName, service.ClientSecretKey)
	}

	serviceID, err := p.AIB.Upsert(ctx, "services", "client_id", service.ClientID, exchangeServiceBody(service, clientSecret))
	if err != nil {
		return nil, fmt.Errorf("creating AIB service: %w", err)
	}
	declaredScopes := make(map[string]bool, len(service.Scopes))
	for _, scope := range service.Scopes {
		declaredScopes[scope.Name] = true
	}
	bindings := make(map[string]string, len(service.Access))
	for _, access := range service.Access {
		for _, scope := range access.Scopes {
			if !declaredScopes[scope] {
				return nil, fmt.Errorf("Agent %q requests undeclared scope %q", access.Agent, scope)
			}
		}
		permissionSetName := projection.ThirdPartyPermissionSetName(service.Namespace, service.Name, access.Agent)
		permissionSetID, err := p.AIB.Upsert(ctx, "permission-sets", "name", permissionSetName, exchangePermissionSetBody(permissionSetName, serviceID, access.Scopes))
		if err != nil {
			return nil, fmt.Errorf("creating AIB permission set %q: %w", permissionSetName, err)
		}
		bindings[access.Agent] = permissionSetID
	}
	return bindings, nil
}

func (p *ExchangeProjector) readSecret(ctx context.Context, namespace, name string) (*corev1.Secret, error) {
	secret := &corev1.Secret{}
	if err := p.Client.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, secret); err != nil {
		return nil, err
	}
	return secret, nil
}

func (p *ExchangeProjector) agentClientID(ctx context.Context, namespace, agent string) (string, error) {
	prefix := strings.TrimSpace(p.OIDCSecretPrefix)
	if prefix == "" {
		prefix = "kaos-oidc"
	}
	name := security.CredentialSecretName(prefix, agent)
	secret, err := p.readSecret(ctx, namespace, name)
	if err != nil {
		return "", fmt.Errorf("reading Keycloak credentials for Agent %q: %w", agent, err)
	}
	clientID := secretValue(secret, credentialClientIDKey)
	if clientID == "" {
		return "", fmt.Errorf("Keycloak credential Secret %s/%s has no client_id", namespace, name)
	}
	return clientID, nil
}

func exchangeServiceBody(service projection.DesiredThirdPartyService, clientSecret string) map[string]any {
	displayName := strings.TrimSpace(service.DisplayName)
	if displayName == "" {
		displayName = service.Name
	}
	body := map[string]any{
		"display_name":        displayName,
		"client_id":           service.ClientID,
		"client_secret":       clientSecret,
		"issuer_uri":          service.IssuerURI,
		"discovery":           map[string]any{"enable_discovery": service.TokenEndpoint == "" && service.AuthorizeEndpoint == ""},
		"protected_resources": service.ProtectedResources,
	}
	if service.TokenEndpoint != "" || service.AuthorizeEndpoint != "" {
		body["endpoints"] = map[string]any{"token_endpoint": service.TokenEndpoint, "authorize_endpoint": service.AuthorizeEndpoint}
	}
	scopes := make([]any, 0, len(service.Scopes))
	for _, scope := range service.Scopes {
		scopes = append(scopes, map[string]any{"scope_value": scope.Name, "description": scope.Description})
	}
	body["scopes"] = scopes
	return body
}

func exchangePermissionSetBody(name, serviceID string, scopes []string) map[string]any {
	return map[string]any{
		"name":        name,
		"description": "KAOS delegated third-party access",
		"service_scopes": []any{map[string]any{
			"service_id": serviceID, "scopes": scopes, "requirement_type": "mandatory",
		}},
	}
}

func exchangeAgentBody(namespace, name, clientID string, permissionSetIDs []string) map[string]any {
	permissionSets := make([]any, 0, len(permissionSetIDs))
	for _, permissionSetID := range permissionSetIDs {
		permissionSets = append(permissionSets, map[string]any{"permission_set_id": permissionSetID, "requirement_type": "mandatory"})
	}
	return map[string]any{
		"client_id":       clientID,
		"external_id":     projection.AgentExternalID(namespace, name),
		"display_name":    name,
		"description":     fmt.Sprintf("KAOS exchange agent %s/%s", namespace, name),
		"permission_sets": permissionSets,
	}
}
