package gateway

import "testing"

func TestConstructHTTPRouteStampsResourceIdentity(t *testing.T) {
	route := constructHTTPRoute(HTTPRouteParams{
		ResourceType: ResourceTypeModelAPI,
		ResourceName: "llama",
		Namespace:    "agents",
		ServiceName:  "modelapi-llama",
		ServicePort:  8000,
	}, Config{GatewayName: "kaos-gateway", GatewayNamespace: "kaos-system"})

	filter := route.Spec.Rules[0].Filters[0]
	if filter.RequestHeaderModifier == nil || len(filter.RequestHeaderModifier.Set) != 1 {
		t.Fatalf("request header modifier = %#v", filter.RequestHeaderModifier)
	}
	header := filter.RequestHeaderModifier.Set[0]
	if header.Name != "x-kaos-target-resource" || header.Value != "kaos://modelapi/agents/llama" {
		t.Fatalf("target resource header = %#v", header)
	}
}

func TestResourceIdentityUsesProjectionSlugs(t *testing.T) {
	if got := ResourceIdentity("agents", ResourceTypeMCP, "github"); got != "kaos://mcpserver/agents/github" {
		t.Fatalf("MCP resource identity = %q", got)
	}
}
