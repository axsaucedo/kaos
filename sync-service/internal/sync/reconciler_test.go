package sync

import (
	"reflect"
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

	"github.com/axsaucedo/kaos/sync-service/internal/projection"
)

func TestToResourceMapsAgentSpec(t *testing.T) {
	obj := &unstructured.Unstructured{Object: map[string]any{
		"metadata": map[string]any{"namespace": "demo", "name": "a"},
		"spec": map[string]any{
			"mcpServers": []any{"github"},
			"modelAPI":   "gpt",
			"agentNetwork": map[string]any{
				"access": []any{"b", "c"},
			},
		},
	}}

	res := toResource(projection.AgentKind, obj)

	if res.Kind != projection.AgentKind || res.Namespace != "demo" || res.Name != "a" {
		t.Fatalf("identity = %+v", res)
	}
	if !reflect.DeepEqual(res.MCPServers, []string{"github"}) {
		t.Fatalf("mcpServers = %v", res.MCPServers)
	}
	if res.ModelAPI != "gpt" {
		t.Fatalf("modelAPI = %q", res.ModelAPI)
	}
	if !reflect.DeepEqual(res.Access, []string{"b", "c"}) {
		t.Fatalf("access = %v", res.Access)
	}
}

func TestToResourceAgentWithoutNetworkHasNoAccess(t *testing.T) {
	obj := &unstructured.Unstructured{Object: map[string]any{
		"metadata": map[string]any{"namespace": "demo", "name": "a"},
		"spec":     map[string]any{"modelAPI": "gpt"},
	}}

	res := toResource(projection.AgentKind, obj)

	if len(res.Access) != 0 {
		t.Fatalf("access = %v, want empty", res.Access)
	}
}

func TestToResourceNonAgentIgnoresSpec(t *testing.T) {
	obj := &unstructured.Unstructured{Object: map[string]any{
		"metadata": map[string]any{"namespace": "demo", "name": "github"},
		"spec":     map[string]any{"agentNetwork": map[string]any{"access": []any{"x"}}},
	}}

	res := toResource("MCPServer", obj)

	if len(res.Access) != 0 || len(res.MCPServers) != 0 || res.ModelAPI != "" {
		t.Fatalf("non-agent picked up agent spec: %+v", res)
	}
}
