package controllers

import (
	"testing"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestMemoryUserScopingEnvUsesUserSecurityMode(t *testing.T) {
	t.Setenv("SECURITY_PDP_ENABLED", "true")
	t.Setenv("SECURITY_USER_AUTH_ISSUER", "https://users.example")

	agent := &kaosv1alpha1.Agent{}
	agent.Spec.Config = &kaosv1alpha1.AgentConfig{Memory: &kaosv1alpha1.MemoryConfig{}}
	model := &kaosv1alpha1.ModelAPI{}
	env := (&AgentReconciler{}).constructEnvVars(
		agent, model, nil, nil, "", "agent", "",
	)

	for _, item := range env {
		if item.Name == "MEMORY_USER_SCOPING" && item.Value == "required" {
			return
		}
	}
	t.Fatal("memory-configured agent did not receive required user scoping")
}

func TestMemoryUserScopingEnvIsNotSetForAgentOnlySecurity(t *testing.T) {
	t.Setenv("SECURITY_PDP_ENABLED", "true")
	t.Setenv("SECURITY_AGENT_AUTH_ISSUER", "https://agents.example")

	agent := &kaosv1alpha1.Agent{}
	agent.Spec.Config = &kaosv1alpha1.AgentConfig{Memory: &kaosv1alpha1.MemoryConfig{}}
	model := &kaosv1alpha1.ModelAPI{}
	env := (&AgentReconciler{}).constructEnvVars(
		agent, model, nil, nil, "", "agent", "",
	)

	for _, item := range env {
		if item.Name == "MEMORY_USER_SCOPING" {
			t.Fatalf("agent-only security unexpectedly enabled user scoping: %#v", item)
		}
	}
}

func TestMemoryUserScopingEnvRequiresSecurityEnforcement(t *testing.T) {
	t.Setenv("SECURITY_USER_AUTH_ISSUER", "https://users.example")

	agent := &kaosv1alpha1.Agent{}
	agent.Spec.Config = &kaosv1alpha1.AgentConfig{Memory: &kaosv1alpha1.MemoryConfig{}}
	model := &kaosv1alpha1.ModelAPI{}
	env := (&AgentReconciler{}).constructEnvVars(
		agent, model, nil, nil, "", "agent", "",
	)

	for _, item := range env {
		if item.Name == "MEMORY_USER_SCOPING" {
			t.Fatalf("unenforced user auth unexpectedly enabled user scoping: %#v", item)
		}
	}
}
