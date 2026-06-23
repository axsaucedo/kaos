package projection

import (
	"reflect"
	"sort"
	"testing"
)

func mcpserver(name string) Resource {
	return Resource{Kind: "MCPServer", Namespace: "demo", Name: name}
}

func modelapi(name string) Resource {
	return Resource{Kind: "ModelAPI", Namespace: "demo", Name: name}
}

func agent(name string, mcpServers []string, modelAPI string) Resource {
	return Resource{Kind: "Agent", Namespace: "demo", Name: name, MCPServers: mcpServers, ModelAPI: modelAPI}
}

func clientIDs(s DesiredState) []string {
	out := make([]string, 0, len(s.Services))
	for _, svc := range s.Services {
		out = append(out, svc.ClientID())
	}
	sort.Strings(out)
	return out
}

func psNames(s DesiredState) []string {
	out := make([]string, 0, len(s.PermissionSets))
	for _, ps := range s.PermissionSets {
		out = append(out, ps.Name())
	}
	sort.Strings(out)
	return out
}

func TestEncodingConventions(t *testing.T) {
	if got := edgeServiceClientID(MCPServer, "demo", "github"); got != "kaos-mcpserver-demo-github" {
		t.Fatalf("service client_id = %q", got)
	}
	if got := edgePermissionSetName(MCPServer, "demo", "github"); got != "kaos:mcpserver:demo:github:call" {
		t.Fatalf("permission set name = %q", got)
	}
	if got := AgentExternalID("demo", "researcher"); got != "kaos://agent/demo/researcher" {
		t.Fatalf("agent external_id = %q", got)
	}
}

func TestProjectFullGraph(t *testing.T) {
	state := Project([]Resource{
		mcpserver("github"),
		mcpserver("slack"),
		modelapi("gpt"),
		agent("researcher", []string{"github"}, "gpt"),
	})

	wantServices := []string{"kaos-mcpserver-demo-github", "kaos-mcpserver-demo-slack", "kaos-modelapi-demo-gpt"}
	if got := clientIDs(state); !reflect.DeepEqual(got, wantServices) {
		t.Fatalf("services = %v, want %v", got, wantServices)
	}
	wantPS := []string{"kaos:mcpserver:demo:github:call", "kaos:modelapi:demo:gpt:call"}
	if got := psNames(state); !reflect.DeepEqual(got, wantPS) {
		t.Fatalf("permission sets = %v, want %v", got, wantPS)
	}
	if len(state.Agents) != 1 {
		t.Fatalf("agents = %d, want 1", len(state.Agents))
	}
	a := state.Agents[0]
	if a.ExternalID() != "kaos://agent/demo/researcher" {
		t.Fatalf("external_id = %q", a.ExternalID())
	}
	wantNames := []string{"kaos:mcpserver:demo:github:call", "kaos:modelapi:demo:gpt:call"}
	if !reflect.DeepEqual(a.PermissionSetNames, wantNames) {
		t.Fatalf("permission_set_names = %v, want %v", a.PermissionSetNames, wantNames)
	}
}

func TestModelAPIEdgeProjectedWithoutMCPServers(t *testing.T) {
	state := Project([]Resource{agent("solo", nil, "gpt")})
	if got := clientIDs(state); !reflect.DeepEqual(got, []string{"kaos-modelapi-demo-gpt"}) {
		t.Fatalf("services = %v", got)
	}
	if got := psNames(state); !reflect.DeepEqual(got, []string{"kaos:modelapi:demo:gpt:call"}) {
		t.Fatalf("permission sets = %v", got)
	}
	if len(state.Agents) != 1 || !reflect.DeepEqual(state.Agents[0].PermissionSetNames, []string{"kaos:modelapi:demo:gpt:call"}) {
		t.Fatalf("agent grants = %+v", state.Agents)
	}
}

func TestAgentWithoutAnyEdgeIsSkipped(t *testing.T) {
	state := Project([]Resource{mcpserver("github"), agent("idle", nil, "")})
	if len(state.Agents) != 0 {
		t.Fatalf("agents = %v, want empty", state.Agents)
	}
	if got := clientIDs(state); !reflect.DeepEqual(got, []string{"kaos-mcpserver-demo-github"}) {
		t.Fatalf("services = %v", got)
	}
}

func TestDeclaredModelAPIYieldsServiceEvenWhenUngranted(t *testing.T) {
	state := Project([]Resource{modelapi("gpt"), agent("idle", nil, "")})
	if got := clientIDs(state); !reflect.DeepEqual(got, []string{"kaos-modelapi-demo-gpt"}) {
		t.Fatalf("services = %v", got)
	}
	if len(state.PermissionSets) != 0 || len(state.Agents) != 0 {
		t.Fatalf("ps=%d agents=%d, want 0/0", len(state.PermissionSets), len(state.Agents))
	}
}

func TestEdgeToUndeclaredMCPServerStillYieldsService(t *testing.T) {
	state := Project([]Resource{agent("researcher", []string{"ghost"}, "")})
	if got := clientIDs(state); !reflect.DeepEqual(got, []string{"kaos-mcpserver-demo-ghost"}) {
		t.Fatalf("services = %v", got)
	}
	if got := psNames(state); !reflect.DeepEqual(got, []string{"kaos:mcpserver:demo:ghost:call"}) {
		t.Fatalf("permission sets = %v", got)
	}
	if len(state.Agents) != 1 || !reflect.DeepEqual(state.Agents[0].PermissionSetNames, []string{"kaos:mcpserver:demo:ghost:call"}) {
		t.Fatalf("agent = %+v", state.Agents)
	}
}

func TestProjectionDeduplicates(t *testing.T) {
	resources := []Resource{
		mcpserver("github"),
		modelapi("gpt"),
		agent("a", []string{"github"}, "gpt"),
		agent("b", []string{"github"}, "gpt"),
	}
	state := Project(resources)
	if len(state.Services) != 2 || len(state.PermissionSets) != 2 || len(state.Agents) != 2 {
		t.Fatalf("svc=%d ps=%d agents=%d, want 2/2/2", len(state.Services), len(state.PermissionSets), len(state.Agents))
	}
}

func TestResolveLogicalIDNamespaceScoped(t *testing.T) {
	if got := ResolveLogicalID("agent", "ns", "n"); got != "kaos://agent/ns/n" {
		t.Fatalf("logical id = %q", got)
	}
}

func TestDefaultResourcesNamespaceScoped(t *testing.T) {
	state := Project([]Resource{mcpserver("github"), agent("researcher", []string{"github"}, "")})
	if !hasService(state, "kaos-mcpserver-demo-github") {
		t.Fatalf("missing service: %v", clientIDs(state))
	}
	if state.Agents[0].ExternalID() != "kaos://agent/demo/researcher" {
		t.Fatalf("external_id = %q", state.Agents[0].ExternalID())
	}
}

func TestAdminBodiesShape(t *testing.T) {
	state := Project([]Resource{mcpserver("github"), agent("researcher", []string{"github"}, "")})
	svc := state.Services[0].AdminBody()
	if svc["client_id"] != "kaos-mcpserver-demo-github" {
		t.Fatalf("svc client_id = %v", svc["client_id"])
	}
	ps := state.PermissionSets[0].AdminBody("svc-123")
	scopes := ps["service_scopes"].([]any)[0].(map[string]any)
	if scopes["service_id"] != "svc-123" {
		t.Fatalf("service_id = %v", scopes["service_id"])
	}
	agentBody := state.Agents[0].AdminBody([]string{"ps-1"})
	if _, leaks := agentBody["client_id"]; leaks {
		t.Fatalf("agent body leaks client_id: %v", agentBody)
	}
	bindings := agentBody["permission_sets"].([]any)
	entry := bindings[0].(map[string]any)
	if entry["permission_set_id"] != "ps-1" || entry["requirement_type"] != "mandatory" {
		t.Fatalf("binding = %v", entry)
	}
}

func TestAdminBodiesCarryNoApprovalStatus(t *testing.T) {
	approvalKeys := map[string]bool{"approved": true, "approval": true, "status": true, "state": true, "decision": true, "granted": true}
	state := Project([]Resource{mcpserver("github"), modelapi("gpt"), agent("researcher", []string{"github"}, "gpt")})

	check := func(body map[string]any, where string) {
		for k := range body {
			if approvalKeys[k] {
				t.Fatalf("%s leaks approval key %q", where, k)
			}
		}
	}
	for _, svc := range state.Services {
		check(svc.AdminBody(), "service body")
	}
	for _, ps := range state.PermissionSets {
		check(ps.AdminBody("svc-id"), "permission-set body")
	}
	for _, a := range state.Agents {
		body := a.AdminBody([]string{"ps-id"})
		check(body, "agent body")
		for _, e := range body["permission_sets"].([]any) {
			entry := e.(map[string]any)
			if len(entry) != 2 || entry["requirement_type"] != "mandatory" {
				t.Fatalf("binding entry = %v", entry)
			}
		}
	}
}

func hasService(s DesiredState, clientID string) bool {
	for _, svc := range s.Services {
		if svc.ClientID() == clientID {
			return true
		}
	}
	return false
}

func hasPS(s DesiredState, name string) bool {
	for _, ps := range s.PermissionSets {
		if ps.Name() == name {
			return true
		}
	}
	return false
}
