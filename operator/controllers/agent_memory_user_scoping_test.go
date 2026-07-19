package controllers

import (
	"testing"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestMemoryPostureEnvUsesUserSecurityMode(t *testing.T) {
	t.Setenv("SECURITY_PDP_ENABLED", "true")
	t.Setenv("SECURITY_USER_AUTH_ISSUER", "https://users.example")

	agent := &kaosv1alpha1.Agent{}
	agent.Spec.Config = &kaosv1alpha1.AgentConfig{Memory: &kaosv1alpha1.MemoryConfig{}}
	model := &kaosv1alpha1.ModelAPI{}
	env := (&AgentReconciler{}).constructEnvVars(
		agent, model, nil, nil, "", "agent", "",
	)

	want := map[string]string{"MEMORY_REQUIRE_PRINCIPAL": "true", "MEMORY_REQUIRE_AGENT_IDENTITY": "true"}
	for _, item := range env {
		delete(want, item.Name)
	}
	if len(want) != 0 {
		t.Fatalf("missing posture env vars: %v", want)
	}
}

func TestMemoryPostureEnvForAgentOnlySecurity(t *testing.T) {
	t.Setenv("SECURITY_PDP_ENABLED", "true")
	t.Setenv("SECURITY_AGENT_AUTH_ISSUER", "https://agents.example")

	agent := &kaosv1alpha1.Agent{}
	agent.Spec.Config = &kaosv1alpha1.AgentConfig{Memory: &kaosv1alpha1.MemoryConfig{}}
	model := &kaosv1alpha1.ModelAPI{}
	env := (&AgentReconciler{}).constructEnvVars(
		agent, model, nil, nil, "", "agent", "",
	)

	gotAgent := false
	for _, item := range env {
		if item.Name == "MEMORY_REQUIRE_PRINCIPAL" {
			t.Fatalf("agent-only security unexpectedly required principal: %#v", item)
		}
		if item.Name == "MEMORY_REQUIRE_AGENT_IDENTITY" && item.Value == "true" {
			gotAgent = true
		}
	}
	if !gotAgent {
		t.Fatal("agent-only security did not require agent identity")
	}
}

func TestMemoryPostureEnvRequiresSecurityEnforcement(t *testing.T) {
	t.Setenv("SECURITY_USER_AUTH_ISSUER", "https://users.example")

	agent := &kaosv1alpha1.Agent{}
	agent.Spec.Config = &kaosv1alpha1.AgentConfig{Memory: &kaosv1alpha1.MemoryConfig{}}
	model := &kaosv1alpha1.ModelAPI{}
	env := (&AgentReconciler{}).constructEnvVars(
		agent, model, nil, nil, "", "agent", "",
	)

	for _, item := range env {
		if item.Name == "MEMORY_REQUIRE_PRINCIPAL" || item.Name == "MEMORY_REQUIRE_AGENT_IDENTITY" {
			t.Fatalf("unenforced auth unexpectedly enabled posture requirement: %#v", item)
		}
	}
}

func TestMemoryStorePostureProjection(t *testing.T) {
	t.Setenv("SECURITY_PDP_ENABLED", "true")
	t.Setenv("SECURITY_USER_AUTH_ISSUER", "https://users.example")
	env := (&MemoryStoreReconciler{}).buildOperationalEnv(&kaosv1alpha1.MemoryStore{})
	got := map[string]string{}
	for _, item := range env {
		got[item.Name] = item.Value
	}
	if got["KAOS_MEMORY_REQUIRE_PRINCIPAL"] != "true" || got["KAOS_MEMORY_REQUIRE_AGENT_IDENTITY"] != "true" {
		t.Fatalf("MemoryStore posture env = %v", got)
	}
}
