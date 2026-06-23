package controllers

import (
	"context"
	"testing"

	"github.com/go-logr/logr"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func routingModelAPI(namespace, name string) *kaosv1alpha1.ModelAPI {
	m := &kaosv1alpha1.ModelAPI{ObjectMeta: metav1.ObjectMeta{Namespace: namespace, Name: name}}
	m.Status.Endpoint = "http://modelapi-" + name + "." + namespace + ".svc.cluster.local:8000"
	return m
}

func TestApplyGatewayRoutingRepointsToGateway(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "svc:9191")
	t.Setenv("SECURITY_GATEWAY_ROUTING_ENABLED", "true")
	t.Setenv("SECURITY_GATEWAY_HOST", "172.18.0.4:80")

	agent := newAgent("demo", "researcher")
	modelapi := routingModelAPI("demo", "gpt")
	mcpServers := map[string]string{"github": "http://mcp-github.demo.svc.cluster.local:8000"}
	peerAgents := map[string]string{"helper": "http://agent-helper.demo.svc.cluster.local:8000"}

	r := &AgentReconciler{}
	r.applyGatewayRouting(context.Background(), agent, modelapi, mcpServers, peerAgents, logr.Discard())

	if got, want := modelapi.Status.Endpoint, "http://172.18.0.4:80/demo/modelapi/gpt"; got != want {
		t.Errorf("modelapi endpoint = %q, want %q", got, want)
	}
	if got, want := mcpServers["github"], "http://172.18.0.4:80/demo/mcp/github"; got != want {
		t.Errorf("mcp endpoint = %q, want %q", got, want)
	}
	if got, want := peerAgents["helper"], "http://172.18.0.4:80/demo/agent/helper"; got != want {
		t.Errorf("peer endpoint = %q, want %q", got, want)
	}
}

func TestApplyGatewayRoutingDisabledLeavesDirectURLs(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "svc:9191")
	t.Setenv("SECURITY_GATEWAY_ROUTING_ENABLED", "")
	t.Setenv("SECURITY_GATEWAY_HOST", "172.18.0.4:80")

	agent := newAgent("demo", "researcher")
	modelapi := routingModelAPI("demo", "gpt")
	direct := modelapi.Status.Endpoint
	mcpServers := map[string]string{"github": "http://mcp-github.demo.svc.cluster.local:8000"}

	r := &AgentReconciler{}
	r.applyGatewayRouting(context.Background(), agent, modelapi, mcpServers, map[string]string{}, logr.Discard())

	if modelapi.Status.Endpoint != direct {
		t.Errorf("modelapi endpoint changed while routing disabled: %q", modelapi.Status.Endpoint)
	}
	if mcpServers["github"] != "http://mcp-github.demo.svc.cluster.local:8000" {
		t.Errorf("mcp endpoint changed while routing disabled: %q", mcpServers["github"])
	}
}

func TestApplyGatewayRoutingNoHostKeepsDirectURLs(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "svc:9191")
	t.Setenv("SECURITY_GATEWAY_ROUTING_ENABLED", "true")
	t.Setenv("SECURITY_GATEWAY_HOST", "")
	// No GATEWAY_NAME configured, so StatusAddress returns "" and routing is skipped.
	t.Setenv("GATEWAY_NAME", "")

	modelapi := routingModelAPI("demo", "gpt")
	direct := modelapi.Status.Endpoint

	r := &AgentReconciler{}
	r.applyGatewayRouting(context.Background(), newAgent("demo", "researcher"), modelapi,
		map[string]string{}, map[string]string{}, logr.Discard())

	if modelapi.Status.Endpoint != direct {
		t.Errorf("modelapi endpoint changed without a resolvable host: %q", modelapi.Status.Endpoint)
	}
}
