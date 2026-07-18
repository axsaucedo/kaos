package projection

import (
	"reflect"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func TestUserGrantDataCompilesSubjectsExplicitRefsAndSelectors(t *testing.T) {
	state := DesiredState{
		Resources: []Resource{
			{Kind: Agent.ResourceKind, Namespace: "demo", Name: "writer", Labels: map[string]string{"team": "docs"}},
			{Kind: MCPServer.ResourceKind, Namespace: "demo", Name: "search", Labels: map[string]string{"team": "docs"}},
			{Kind: ModelAPI.ResourceKind, Namespace: "other", Name: "private", Labels: map[string]string{"team": "docs"}},
		},
		AccessGrants: []AccessGrant{{
			Namespace: "demo",
			Subjects:  []AccessGrantSubject{{Kind: "User", Name: "alice@example.com"}, {Kind: "Group", Name: "/editors"}},
			Resources: []AccessGrantResource{
				{Kind: MemoryStore.ResourceKind, Name: "memory"},
				{Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"team": "docs"}}},
				{Kind: MemoryStore.ResourceKind, Name: "memory"},
			},
		}},
	}

	want := []string{"kaos://agent/demo/writer", "kaos://mcpserver/demo/search", "kaos://memorystore/demo/memory"}
	got := UserGrantData(state)
	if !reflect.DeepEqual(got["user:alice@example.com"], want) {
		t.Fatalf("user grants = %v, want %v", got["user:alice@example.com"], want)
	}
	if !reflect.DeepEqual(got["group:/editors"], want) {
		t.Fatalf("group grants = %v, want %v", got["group:/editors"], want)
	}
	for _, resource := range got["user:alice@example.com"] {
		if resource == "kaos://modelapi/other/private" {
			t.Fatal("selector crossed namespace boundary")
		}
	}
}
