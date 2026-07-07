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

func peerAgent(name string, access []string) Resource {
	return Resource{Kind: "Agent", Namespace: "demo", Name: name, Access: access}
}

func TestAgentEncodingConventions(t *testing.T) {
	if got := edgeServiceClientID(Agent, "demo", "planner"); got != "kaos-agent-demo-planner" {
		t.Fatalf("agent service client_id = %q", got)
	}
	if got := edgePermissionSetName(Agent, "demo", "planner"); got != "kaos:agent:demo:planner:call" {
		t.Fatalf("agent permission set name = %q", got)
	}
}

func TestAgentAccessEdgeProjected(t *testing.T) {
	state := Project([]Resource{peerAgent("a", []string{"b"}), peerAgent("b", nil)})
	if !hasService(state, "kaos-agent-demo-b") {
		t.Fatalf("missing peer service: %v", clientIDs(state))
	}
	if !hasPS(state, "kaos:agent:demo:b:call") {
		t.Fatalf("missing peer permission set: %v", psNames(state))
	}
	if len(state.Agents) != 1 || state.Agents[0].ExternalID() != "kaos://agent/demo/a" {
		t.Fatalf("agents = %+v, want only a bound", state.Agents)
	}
	if !reflect.DeepEqual(state.Agents[0].PermissionSetNames, []string{"kaos:agent:demo:b:call"}) {
		t.Fatalf("a grants = %v", state.Agents[0].PermissionSetNames)
	}
}

func TestAgentAccessSelfEdgeSkipped(t *testing.T) {
	state := Project([]Resource{peerAgent("a", []string{"a"})})
	if len(state.Services) != 0 || len(state.PermissionSets) != 0 || len(state.Agents) != 0 {
		t.Fatalf("self edge produced svc=%d ps=%d agents=%d, want 0/0/0",
			len(state.Services), len(state.PermissionSets), len(state.Agents))
	}
}

func TestAgentAccessEmptyEdgeSkipped(t *testing.T) {
	state := Project([]Resource{peerAgent("a", []string{""})})
	if len(state.Agents) != 0 {
		t.Fatalf("empty edge produced agents = %+v, want none", state.Agents)
	}
}

func TestAgentAccessDeduplicatesSharedPeer(t *testing.T) {
	state := Project([]Resource{
		peerAgent("a", []string{"shared"}),
		peerAgent("b", []string{"shared"}),
		peerAgent("shared", nil),
	})
	if !hasService(state, "kaos-agent-demo-shared") {
		t.Fatalf("missing shared service: %v", clientIDs(state))
	}
	svcCount := 0
	for _, svc := range state.Services {
		if svc.ClientID() == "kaos-agent-demo-shared" {
			svcCount++
		}
	}
	if svcCount != 1 {
		t.Fatalf("shared peer service count = %d, want 1", svcCount)
	}
	if len(state.Agents) != 2 {
		t.Fatalf("agents = %d, want 2 (a and b)", len(state.Agents))
	}
}

func TestAgentAccessCombinesWithMCPAndModelEdges(t *testing.T) {
	state := Project([]Resource{
		mcpserver("github"),
		modelapi("gpt"),
		{Kind: "Agent", Namespace: "demo", Name: "a", MCPServers: []string{"github"}, ModelAPI: "gpt", Access: []string{"b"}},
		peerAgent("b", nil),
	})
	want := []string{"kaos:agent:demo:b:call", "kaos:mcpserver:demo:github:call", "kaos:modelapi:demo:gpt:call"}
	if len(state.Agents) != 1 {
		t.Fatalf("agents = %d, want 1", len(state.Agents))
	}
	got := append([]string(nil), state.Agents[0].PermissionSetNames...)
	sort.Strings(got)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("a grants = %v, want %v", got, want)
	}
}

func TestAgentAccessToUndeclaredPeerStillYieldsService(t *testing.T) {
	state := Project([]Resource{peerAgent("a", []string{"ghost"})})
	if !hasService(state, "kaos-agent-demo-ghost") {
		t.Fatalf("missing ghost peer service: %v", clientIDs(state))
	}
	if !hasPS(state, "kaos:agent:demo:ghost:call") {
		t.Fatalf("missing ghost permission set: %v", psNames(state))
	}
}
