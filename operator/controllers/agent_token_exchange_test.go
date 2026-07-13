package controllers

import (
	"context"
	"encoding/json"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func TestAgentTokenExchangeConfigIncludesOnlyReflectedTargets(t *testing.T) {
	t.Setenv("TOKEN_EXCHANGE_ENABLED", "true")
	t.Setenv("SECURITY_AGENT_AUTH_IDENTITY_PROVIDER", "oidc")
	t.Setenv("SECURITY_AGENT_AUTH_ISSUER", "https://keycloak.example/realms/kaos")
	scheme := newTestScheme(t)
	reflection := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: exchangeReflectionName},
		Data: map[string]string{
			"researcher": `["https://uploads.github.com/","https://api.github.com/"]`,
		},
	}
	r := &AgentReconciler{Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(reflection).Build()}

	value, err := r.tokenExchangeConfig(context.Background(), newAgent("demo", "researcher"))
	if err != nil {
		t.Fatalf("tokenExchangeConfig: %v", err)
	}
	var config agentTokenExchangeConfig
	if err := json.Unmarshal([]byte(value), &config); err != nil {
		t.Fatalf("unmarshal config: %v", err)
	}
	if len(config.Targets) != 2 || config.Targets[0] != "https://api.github.com/" || config.Targets[1] != "https://uploads.github.com/" {
		t.Fatalf("targets = %#v", config.Targets)
	}

	unbound, err := r.tokenExchangeConfig(context.Background(), newAgent("demo", "unbound"))
	if err != nil || unbound != "" {
		t.Fatalf("unbound config = %q, %v", unbound, err)
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
