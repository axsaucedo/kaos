package aib

import (
	"testing"

	"github.com/axsaucedo/kaos/operator/internal/projection"
)

func TestServiceBodyShape(t *testing.T) {
	svc := projection.DesiredService{Namespace: "demo", Name: "github", Kind: projection.MCPServer}
	body := ServiceBody(svc)
	if body["client_id"] != "kaos-mcpserver-demo-github" {
		t.Fatalf("svc client_id = %v", body["client_id"])
	}
	if body["issuer_uri"] != "https://kaos.local/mcpserver/demo/github" {
		t.Fatalf("issuer_uri = %v", body["issuer_uri"])
	}
	scopes := body["scopes"].([]any)[0].(map[string]any)
	if scopes["scope_value"] != projection.CallScope {
		t.Fatalf("scope_value = %v", scopes["scope_value"])
	}
}

func TestPermissionSetBodyReferencesService(t *testing.T) {
	ps := projection.DesiredPermissionSet{Namespace: "demo", Target: "github", Kind: projection.MCPServer}
	body := PermissionSetBody(ps, "svc-123")
	scopes := body["service_scopes"].([]any)[0].(map[string]any)
	if scopes["service_id"] != "svc-123" {
		t.Fatalf("service_id = %v", scopes["service_id"])
	}
	if scopes["requirement_type"] != "mandatory" {
		t.Fatalf("requirement_type = %v", scopes["requirement_type"])
	}
}

func TestAgentBodyBindsPermissionSetsWithoutLeakingClientID(t *testing.T) {
	agent := projection.DesiredAgent{Namespace: "demo", Name: "researcher"}
	body := AgentBody(agent, []string{"ps-1"})
	if _, leaks := body["client_id"]; leaks {
		t.Fatalf("agent body leaks client_id: %v", body)
	}
	if body["display_name"] != agent.ExternalID() {
		t.Fatalf("display_name = %v", body["display_name"])
	}
	entry := body["permission_sets"].([]any)[0].(map[string]any)
	if entry["permission_set_id"] != "ps-1" || entry["requirement_type"] != "mandatory" {
		t.Fatalf("binding = %v", entry)
	}
}

func TestAdminBodiesCarryNoApprovalStatus(t *testing.T) {
	approvalKeys := map[string]bool{"approved": true, "approval": true, "status": true, "state": true, "decision": true, "granted": true}
	check := func(body map[string]any, where string) {
		for k := range body {
			if approvalKeys[k] {
				t.Fatalf("%s leaks approval key %q", where, k)
			}
		}
	}

	svc := projection.DesiredService{Namespace: "demo", Name: "github", Kind: projection.MCPServer}
	ps := projection.DesiredPermissionSet{Namespace: "demo", Target: "github", Kind: projection.MCPServer}
	agent := projection.DesiredAgent{Namespace: "demo", Name: "researcher"}

	check(ServiceBody(svc), "service body")
	check(PermissionSetBody(ps, "svc-id"), "permission-set body")
	body := AgentBody(agent, []string{"ps-id"})
	check(body, "agent body")
	for _, e := range body["permission_sets"].([]any) {
		entry := e.(map[string]any)
		if len(entry) != 2 || entry["requirement_type"] != "mandatory" {
			t.Fatalf("binding entry = %v", entry)
		}
	}
}
