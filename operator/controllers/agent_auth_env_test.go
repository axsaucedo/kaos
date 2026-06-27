package controllers

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func newAgent(namespace, name string) *kaosv1alpha1.Agent {
	return &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: namespace, Name: name},
	}
}

func envByName(env []corev1.EnvVar, name string) (corev1.EnvVar, bool) {
	for _, e := range env {
		if e.Name == name {
			return e, true
		}
	}
	return corev1.EnvVar{}, false
}

func TestBuildAgentAuthEnvVarsDisabled(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "")
	t.Setenv("SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX", "")

	if env := buildAgentAuthEnvVars(newAgent("demo", "researcher")); env != nil {
		t.Errorf("expected no agent-auth env when credential mounting is disabled, got %v", env)
	}
}

func TestBuildAgentAuthEnvVarsDisabledWithoutExtAuthz(t *testing.T) {
	// A prefix alone must not enable mounting; ext_authz must also be set.
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "")
	t.Setenv("SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX", "kaos-aib")

	if env := buildAgentAuthEnvVars(newAgent("demo", "researcher")); env != nil {
		t.Errorf("expected no agent-auth env without ext_authz, got %v", env)
	}
}

func TestBuildAgentAuthEnvVarsEnabled(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "aib-ext-authz.aib-system:9002")
	t.Setenv("SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX", "kaos-aib")
	t.Setenv("SECURITY_AGENT_AUTH_ISSUER", "http://aib-enduser.aib-system.svc.cluster.local:8000")

	env := buildAgentAuthEnvVars(newAgent("demo", "researcher"))

	actor, ok := envByName(env, "AGENT_AUTH_IDENTITY")
	if !ok || actor.Value != "kaos://agent/demo/researcher" {
		t.Errorf("AGENT_AUTH_IDENTITY = %q (found=%v), want kaos://agent/demo/researcher", actor.Value, ok)
	}

	clientID, ok := envByName(env, "AGENT_AUTH_CLIENT_ID")
	if !ok || clientID.ValueFrom == nil || clientID.ValueFrom.SecretKeyRef == nil {
		t.Fatalf("AGENT_AUTH_CLIENT_ID missing a secretKeyRef")
	}
	ref := clientID.ValueFrom.SecretKeyRef
	if ref.Name != "kaos-aib-researcher" || ref.Key != "client_id" {
		t.Errorf("AGENT_AUTH_CLIENT_ID ref = %s/%s, want kaos-aib-researcher/client_id", ref.Name, ref.Key)
	}
	if ref.Optional == nil || !*ref.Optional {
		t.Errorf("AGENT_AUTH_CLIENT_ID secret ref must be optional so the pod can start before the Secret exists")
	}

	secret, ok := envByName(env, "AGENT_AUTH_CLIENT_SECRET")
	if !ok || secret.ValueFrom == nil || secret.ValueFrom.SecretKeyRef == nil ||
		secret.ValueFrom.SecretKeyRef.Key != "client_secret" {
		t.Errorf("AGENT_AUTH_CLIENT_SECRET missing a client_secret secretKeyRef")
	}

	endpoint, ok := envByName(env, "AGENT_AUTH_TOKEN_ENDPOINT")
	if !ok || endpoint.Value != "http://aib-enduser.aib-system.svc.cluster.local:8000/oauth2/token" {
		t.Errorf("AGENT_AUTH_TOKEN_ENDPOINT = %q, want the issuer token endpoint", endpoint.Value)
	}
}

func TestBuildAgentAuthEnvVarsWithoutIssuer(t *testing.T) {
	t.Setenv("SECURITY_AGENT_AUTH_EXT_AUTHZ_URL", "aib-ext-authz.aib-system:9002")
	t.Setenv("SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX", "kaos-aib")
	t.Setenv("SECURITY_AGENT_AUTH_ISSUER", "")

	env := buildAgentAuthEnvVars(newAgent("demo", "researcher"))

	if _, ok := envByName(env, "AGENT_AUTH_TOKEN_ENDPOINT"); ok {
		t.Errorf("AGENT_AUTH_TOKEN_ENDPOINT must be omitted when no issuer is configured")
	}
	if _, ok := envByName(env, "AGENT_AUTH_CLIENT_ID"); !ok {
		t.Errorf("credentials must still be mounted without an issuer")
	}
}
