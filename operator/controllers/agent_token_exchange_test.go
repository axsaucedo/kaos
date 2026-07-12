package controllers

import (
	"context"
	"encoding/json"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestAgentTokenExchangeConfigIncludesOnlyBoundTargets(t *testing.T) {
	t.Setenv("TOKEN_EXCHANGE_ENABLED", "true")
	t.Setenv("SECURITY_AGENT_AUTH_IDENTITY_PROVIDER", "oidc")
	t.Setenv("SECURITY_AGENT_AUTH_ISSUER", "https://keycloak.example/realms/kaos")
	scheme := newTestScheme(t)
	github := &kaosv1alpha1.ThirdPartyService{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "github"},
		Spec: kaosv1alpha1.ThirdPartyServiceSpec{
			ProtectedResources: []string{"https://uploads.github.com/", "https://api.github.com/"},
			Access:             []kaosv1alpha1.ThirdPartyServiceAccess{{Agent: "researcher", Scopes: []string{"repo"}}},
		},
	}
	drive := &kaosv1alpha1.ThirdPartyService{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "drive"},
		Spec: kaosv1alpha1.ThirdPartyServiceSpec{
			ProtectedResources: []string{"https://drive.example/"},
			Access:             []kaosv1alpha1.ThirdPartyServiceAccess{{Agent: "other", Scopes: []string{"read"}}},
		},
	}
	r := &AgentReconciler{Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(github, drive).Build()}

	value, err := r.tokenExchangeConfig(context.Background(), newAgent("demo", "researcher"))
	if err != nil {
		t.Fatalf("tokenExchangeConfig: %v", err)
	}
	var config agentTokenExchangeConfig
	if err := json.Unmarshal([]byte(value), &config); err != nil {
		t.Fatalf("unmarshal config: %v", err)
	}
	if config.Issuer != "https://keycloak.example/realms/kaos" || config.TokenEndpoint != "https://keycloak.example/realms/kaos/protocol/openid-connect/token" {
		t.Fatalf("unexpected Keycloak config: %#v", config)
	}
	if config.Audience != "token-exchange-broker" {
		t.Fatalf("audience = %q", config.Audience)
	}
	if len(config.Targets) != 2 || config.Targets[0] != "https://api.github.com/" || config.Targets[1] != "https://uploads.github.com/" {
		t.Fatalf("targets = %#v", config.Targets)
	}
}

func TestAgentTokenExchangeConfigDisabled(t *testing.T) {
	t.Setenv("TOKEN_EXCHANGE_ENABLED", "false")
	r := &AgentReconciler{}
	value, err := r.tokenExchangeConfig(context.Background(), newAgent("demo", "researcher"))
	if err != nil || value != "" {
		t.Fatalf("disabled config = %q, %v", value, err)
	}
}
