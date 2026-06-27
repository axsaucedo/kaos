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
}

const envExtAuthzURL = "SECURITY_AGENT_AUTH_EXT_AUTHZ_URL"

// GetConfig reads security configuration from environment variables.
func GetConfig() Config {
	return Config{
		ExtAuthzURL: os.Getenv(envExtAuthzURL),
	}
}

// IsOperational reports whether gateway authorization enforcement is configured.
// The operator only generates authorization policies when this returns true.
func (c Config) IsOperational() bool {
	return strings.TrimSpace(c.ExtAuthzURL) != ""
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
