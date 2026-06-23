// Package security provides operator-wide configuration for resource-level
// authorization enforcement at the gateway. When configured, the operator
// attaches an external authorization (ext_authz) check to protected routes so
// that requests are allowed or denied based on the calling agent's granted
// permissions.
package security

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config holds operator-wide security configuration read from the environment.
// Security is enabled by the presence of an agent-auth ext_authz URL: when
// ExtAuthzURL is empty the operator generates no authorization policies and
// existing routing behavior is unchanged.
type Config struct {
	// ExtAuthzURL is the host:port of the external authorization (ext_authz)
	// access-check gRPC backend (agentAuth.extAuthzUrl). An empty value means
	// gateway authorization enforcement is disabled.
	ExtAuthzURL string

	// Issuer is the agent-auth OIDC issuer URL (agentAuth.issuer): the broker
	// that mints agent actor tokens. It is propagated to agent pods so they can
	// obtain an actor token from their mounted credentials.
	Issuer string

	// CredentialSecretPrefix is the name prefix of the per-agent credential
	// Secret provisioned by the sync service (agentAuth.credentialSecretPrefix).
	// An empty value disables credential mounting into agent pods.
	CredentialSecretPrefix string

	// UserIssuer is the user-auth OIDC issuer URL (userAuth.issuer): the identity
	// provider (e.g. Keycloak) that issues human user subject tokens. When set, a
	// user jwt_authn provider is emitted on protected routes. Empty means no user
	// provider is generated (agent-only / autonomous installs).
	UserIssuer string

	// UserAudience is the expected audience claim for user subject tokens
	// (userAuth.audience). Validated by the user jwt_authn provider when set.
	UserAudience string

	// UserJWKSURIOverride optionally overrides the user provider's JWKS endpoint
	// (userAuth.jwksUri). When empty it is derived from UserIssuer using the
	// standard OIDC realm path.
	UserJWKSURIOverride string

	// ExtProcURL is the host:port of the AIB external-processing (ext_proc)
	// token-exchange gRPC backend (agentAuth.extProcUrl). When set, the operator
	// emits an EnvoyExtensionPolicy on protected routes so the gateway can perform
	// an RFC 8693 token exchange and replace the upstream Authorization header.
	// An empty value means token-exchange is disabled and existing routing is
	// unchanged. It is independent of ExtAuthzURL.
	ExtProcURL string

	// GatewayNamespace is the namespace of the Envoy Gateway data plane
	// (security.gatewayNamespace). It is the ingress source allowed by the
	// generated NetworkPolicy so the Gateway can reach protected workloads. An
	// empty value defaults to "envoy-gateway-system".
	GatewayNamespace string

	// OperatorNamespace is the namespace the operator runs in. It is the ingress
	// source allowed by the generated NetworkPolicy so the operator can still poll
	// workload ClusterIP status endpoints. It is read from SECURITY_OPERATOR_NAMESPACE,
	// falling back to POD_NAMESPACE; an empty value defaults to "kaos-system".
	OperatorNamespace string

	// NetworkPolicyDisabled is an escape hatch (security.networkPolicy.enabled=false)
	// that suppresses NetworkPolicy generation even when security is operational, for
	// CNIs that misbehave or clusters that manage isolation externally.
	NetworkPolicyDisabled bool
}

const (
	envExtAuthzURL            = "SECURITY_AGENT_AUTH_EXT_AUTHZ_URL"
	envExtProcURL             = "SECURITY_AGENT_AUTH_EXT_PROC_URL"
	envIssuer                 = "SECURITY_AGENT_AUTH_ISSUER"
	envCredentialSecretPrefix = "SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX"
	envUserIssuer             = "SECURITY_USER_AUTH_ISSUER"
	envUserAudience           = "SECURITY_USER_AUTH_AUDIENCE"
	envUserJWKSURI            = "SECURITY_USER_AUTH_JWKS_URI"
	envGatewayNamespace       = "SECURITY_GATEWAY_NAMESPACE"
	envOperatorNamespace      = "SECURITY_OPERATOR_NAMESPACE"
	envPodNamespace           = "POD_NAMESPACE"
	envNetworkPolicyDisabled  = "SECURITY_NETWORK_POLICY_DISABLED"
)

// Default namespaces used by NetworkPolicy ingress rules when not configured.
const (
	defaultGatewayNamespace  = "envoy-gateway-system"
	defaultOperatorNamespace = "kaos-system"
)

// GetConfig reads security configuration from environment variables.
func GetConfig() Config {
	operatorNamespace := os.Getenv(envOperatorNamespace)
	if strings.TrimSpace(operatorNamespace) == "" {
		operatorNamespace = os.Getenv(envPodNamespace)
	}
	return Config{
		ExtAuthzURL:            os.Getenv(envExtAuthzURL),
		Issuer:                 os.Getenv(envIssuer),
		CredentialSecretPrefix: os.Getenv(envCredentialSecretPrefix),
		UserIssuer:             os.Getenv(envUserIssuer),
		UserAudience:           os.Getenv(envUserAudience),
		UserJWKSURIOverride:    os.Getenv(envUserJWKSURI),
		ExtProcURL:             os.Getenv(envExtProcURL),
		GatewayNamespace:       os.Getenv(envGatewayNamespace),
		OperatorNamespace:      operatorNamespace,
		NetworkPolicyDisabled:  parseBoolEnv(envNetworkPolicyDisabled),
	}
}

// parseBoolEnv reads a boolean environment variable, returning false when the
// variable is unset or not a recognizable truthy value.
func parseBoolEnv(key string) bool {
	v, err := strconv.ParseBool(strings.TrimSpace(os.Getenv(key)))
	if err != nil {
		return false
	}
	return v
}

// IsOperational reports whether gateway authorization enforcement is configured.
// The operator only generates authorization policies when this returns true.
func (c Config) IsOperational() bool {
	return strings.TrimSpace(c.ExtAuthzURL) != ""
}

// CredentialMountingEnabled reports whether the operator should mount per-agent
// AIB credentials into agent pods. This requires security to be operational and a
// credential Secret prefix to be configured.
func (c Config) CredentialMountingEnabled() bool {
	return c.IsOperational() && strings.TrimSpace(c.CredentialSecretPrefix) != ""
}

// CredentialSecretName returns the name of the per-agent credential Secret for the
// given agent, using the configured prefix. It matches the name the sync service
// writes, so the operator can mount it without coordination.
func (c Config) CredentialSecretName(agentName string) string {
	return fmt.Sprintf("%s-%s", strings.TrimSpace(c.CredentialSecretPrefix), agentName)
}

// TokenEndpoint returns the agent-auth token endpoint derived from the issuer, or an
// empty string when no issuer is configured.
func (c Config) TokenEndpoint() string {
	issuer := strings.TrimRight(strings.TrimSpace(c.Issuer), "/")
	if issuer == "" {
		return ""
	}
	return issuer + "/oauth2/token"
}

// credentialMountDir is the directory into which the per-agent credential Secret is
// projected in agent pods. The client_secret is exposed as a file under this directory
// so the runtime can re-read it on rotation rather than relying on a static env value.
const credentialMountDir = "/var/run/aib"

// credentialSecretKey is the Secret data key holding the agent's client secret.
const credentialSecretKey = "client_secret"

// CredentialMountDir returns the directory under which the credential Secret is mounted.
func (c Config) CredentialMountDir() string {
	return credentialMountDir
}

// CredentialSecretKey returns the Secret data key holding the agent's client secret.
func (c Config) CredentialSecretKey() string {
	return credentialSecretKey
}

// CredentialSecretFilePath returns the absolute path of the mounted client_secret file
// that the runtime reads (and re-reads on rotation) to mint actor tokens.
func (c Config) CredentialSecretFilePath() string {
	return credentialMountDir + "/" + credentialSecretKey
}

// JWTEnabled reports whether the operator should emit jwt_authn providers on
// protected routes. It is true when either the agent issuer or the user issuer
// is configured. This is independent of IsOperational (which gates ext_authz):
// the jwt block is only rendered when at least one issuer is known.
func (c Config) JWTEnabled() bool {
	return strings.TrimSpace(c.Issuer) != "" || strings.TrimSpace(c.UserIssuer) != ""
}

// AgentJWKSURI returns the JWKS endpoint for the agent (actor) provider, derived
// from the agent-auth issuer. The broker publishes its signing keys at
// "<issuer>/oauth2/jwks.json". It returns an empty string when no issuer is set.
func (c Config) AgentJWKSURI() string {
	issuer := strings.TrimRight(strings.TrimSpace(c.Issuer), "/")
	if issuer == "" {
		return ""
	}
	return issuer + "/oauth2/jwks.json"
}

// UserJWKSURI returns the JWKS endpoint for the user (subject) provider. An
// explicit override (userAuth.jwksUri) takes precedence; otherwise it is derived
// from the user issuer using the standard OIDC realm path
// "<issuer>/protocol/openid-connect/certs" (Keycloak/OIDC). It returns an empty
// string when neither an override nor a user issuer is configured.
func (c Config) UserJWKSURI() string {
	if override := strings.TrimSpace(c.UserJWKSURIOverride); override != "" {
		return override
	}
	issuer := strings.TrimRight(strings.TrimSpace(c.UserIssuer), "/")
	if issuer == "" {
		return ""
	}
	return issuer + "/protocol/openid-connect/certs"
}

// ExtProcEnabled reports whether the operator should emit an EnvoyExtensionPolicy
// (ext_proc token exchange) on protected routes. It is true when ExtProcURL is
// configured. This is independent of IsOperational (which gates ext_authz): a
// deployment may enable token exchange without changing the ext_authz wiring.
func (c Config) ExtProcEnabled() bool {
	return strings.TrimSpace(c.ExtProcURL) != ""
}

// NetworkPolicyEnabled reports whether the operator should generate a
// NetworkPolicy for each protected workload. It requires security to be
// operational and the escape hatch not to be set. When true, direct
// workload-to-workload application traffic is denied so the Gateway cannot be
// bypassed.
func (c Config) NetworkPolicyEnabled() bool {
	return c.IsOperational() && !c.NetworkPolicyDisabled
}

// GatewayNamespaceOrDefault returns the configured Envoy Gateway data-plane
// namespace, defaulting to "envoy-gateway-system" when unset. It is the ingress
// source allowed by generated NetworkPolicies.
func (c Config) GatewayNamespaceOrDefault() string {
	if ns := strings.TrimSpace(c.GatewayNamespace); ns != "" {
		return ns
	}
	return defaultGatewayNamespace
}

// OperatorNamespaceOrDefault returns the namespace the operator runs in,
// defaulting to "kaos-system" when neither SECURITY_OPERATOR_NAMESPACE nor
// POD_NAMESPACE is set. It is the ingress source allowed by generated
// NetworkPolicies so the operator can poll workload status endpoints.
func (c Config) OperatorNamespaceOrDefault() string {
	if ns := strings.TrimSpace(c.OperatorNamespace); ns != "" {
		return ns
	}
	return defaultOperatorNamespace
}

// ExtAuthzBackendRef parses the configured ext_authz host:port URL into the
// Kubernetes Service name, namespace, and port used to build the SecurityPolicy
// gRPC backendRef. The host is expected as a Service DNS name in the form
// "name[.namespace[.svc.cluster.local]]"; the namespace is empty when not present.
func (c Config) ExtAuthzBackendRef() (name, namespace string, port int, err error) {
	return parseServiceHostPort(c.ExtAuthzURL, "ext_authz")
}

// ExtProcBackendRef parses the configured ext_proc host:port URL into the
// Kubernetes Service name, namespace, and port used to build the
// EnvoyExtensionPolicy gRPC backendRef. The host is expected as a Service DNS
// name in the form "name[.namespace[.svc.cluster.local]]"; the namespace is empty
// when not present.
func (c Config) ExtProcBackendRef() (name, namespace string, port int, err error) {
	return parseServiceHostPort(c.ExtProcURL, "ext_proc")
}

// parseServiceHostPort parses a "host:port" Service DNS URL into name, namespace,
// and port. The label argument names the field in error messages. The host is
// expected as "name[.namespace[.svc.cluster.local]]"; namespace is empty when the
// host is a bare service name.
func parseServiceHostPort(rawURL, label string) (name, namespace string, port int, err error) {
	url := strings.TrimSpace(rawURL)
	if url == "" {
		return "", "", 0, fmt.Errorf("%s URL is empty", label)
	}

	host, portStr, found := strings.Cut(url, ":")
	if !found || host == "" || portStr == "" {
		return "", "", 0, fmt.Errorf("%s URL %q must be in host:port form", label, url)
	}
	port, err = strconv.Atoi(portStr)
	if err != nil || port <= 0 {
		return "", "", 0, fmt.Errorf("%s URL %q has an invalid port", label, url)
	}

	labels := strings.Split(host, ".")
	name = labels[0]
	if len(labels) > 1 {
		namespace = labels[1]
	}
	if name == "" {
		return "", "", 0, fmt.Errorf("%s URL %q has an empty service name", label, url)
	}
	return name, namespace, port, nil
}
