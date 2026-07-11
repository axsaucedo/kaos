package projection

import (
	"reflect"
	"testing"
)

func TestGrantDataMapsActorToResourceIDs(t *testing.T) {
	state := Project([]Resource{
		mcpserver("github"),
		modelapi("gpt"),
		agent("researcher", []string{"github"}, "gpt"),
	})

	grants := GrantData(state)

	got, ok := grants["kaos://agent/demo/researcher"]
	if !ok {
		t.Fatalf("missing actor entry: %v", grants)
	}
	want := []string{"kaos://mcpserver/demo/github", "kaos://modelapi/demo/gpt"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("grants = %v, want %v", got, want)
	}
}

func TestGrantDataDeduplicatesAndSorts(t *testing.T) {
	// An agent that reaches the same peer twice must yield a single, sorted entry.
	res := Resource{Kind: "Agent", Namespace: "demo", Name: "a", Access: []string{"c", "b", "b"}}
	state := Project([]Resource{res})

	grants := GrantData(state)
	got := grants["kaos://agent/demo/a"]
	want := []string{"kaos://agent/demo/b", "kaos://agent/demo/c"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("grants = %v, want %v", got, want)
	}
}

func TestGrantDataOmitsAgentsWithoutEdges(t *testing.T) {
	// Agents with no edges are skipped by Project, so they carry no grant entry.
	state := Project([]Resource{agent("lonely", nil, "")})
	if len(GrantData(state)) != 0 {
		t.Fatalf("expected no grants, got %v", GrantData(state))
	}
}
