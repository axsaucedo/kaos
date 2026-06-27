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
}

const (
	envExtAuthzURL            = "SECURITY_AGENT_AUTH_EXT_AUTHZ_URL"
	envIssuer                 = "SECURITY_AGENT_AUTH_ISSUER"
	envCredentialSecretPrefix = "SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX"
)

// GetConfig reads security configuration from environment variables.
func GetConfig() Config {
	return Config{
		ExtAuthzURL:            os.Getenv(envExtAuthzURL),
		Issuer:                 os.Getenv(envIssuer),
		CredentialSecretPrefix: os.Getenv(envCredentialSecretPrefix),
	}
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

// ExtAuthzBackendRef parses the configured ext_authz host:port URL into the
// Kubernetes Service name, namespace, and port used to build the SecurityPolicy
// gRPC backendRef. The host is expected as a Service DNS name in the form
// "name[.namespace[.svc.cluster.local]]"; the namespace is empty when not present.
func (c Config) ExtAuthzBackendRef() (name, namespace string, port int, err error) {
	url := strings.TrimSpace(c.ExtAuthzURL)
	if url == "" {
		return "", "", 0, fmt.Errorf("ext_authz URL is empty")
	}

	host, portStr, found := strings.Cut(url, ":")
	if !found || host == "" || portStr == "" {
		return "", "", 0, fmt.Errorf("ext_authz URL %q must be in host:port form", url)
	}
	port, err = strconv.Atoi(portStr)
	if err != nil || port <= 0 {
		return "", "", 0, fmt.Errorf("ext_authz URL %q has an invalid port", url)
	}

	labels := strings.Split(host, ".")
	name = labels[0]
	if len(labels) > 1 {
		namespace = labels[1]
	}
	if name == "" {
		return "", "", 0, fmt.Errorf("ext_authz URL %q has an empty service name", url)
	}
	return name, namespace, port, nil
}
