// Package security provides operator-wide configuration for resource-level
// authorization enforcement at the gateway. When enabled, the operator attaches
// an external authorization check to protected routes so that requests are
// allowed or denied based on the calling agent's granted permissions.
package security

import (
	"fmt"
	"os"
	"strconv"
)

// Config holds operator-wide authorization configuration read from the
// environment. When Enabled is false the operator generates no authorization
// policies and existing routing behavior is unchanged.
type Config struct {
	// Enabled turns on generation of authorization policies for protected routes.
	Enabled bool
	// ExtAuthzServiceName is the in-cluster Service name of the external
	// authorization (access-check) gRPC backend.
	ExtAuthzServiceName string
	// ExtAuthzServiceNamespace is the namespace of the external authorization Service.
	ExtAuthzServiceNamespace string
	// ExtAuthzServicePort is the gRPC port of the external authorization Service.
	ExtAuthzServicePort int
	// DefaultAction is the action recorded for a protected resource when a route
	// does not specify a more specific one.
	DefaultAction string
}

const (
	defaultExtAuthzPort  = 9191
	defaultDefaultAction = "access"
	envEnabled           = "SECURITY_ENABLED"
	envExtAuthzName      = "SECURITY_EXTAUTHZ_SERVICE_NAME"
	envExtAuthzNamespace = "SECURITY_EXTAUTHZ_SERVICE_NAMESPACE"
	envExtAuthzPort      = "SECURITY_EXTAUTHZ_SERVICE_PORT"
	envDefaultAction     = "SECURITY_DEFAULT_ACTION"
)

// GetConfig reads authorization configuration from environment variables.
func GetConfig() Config {
	return Config{
		Enabled:                  os.Getenv(envEnabled) == "true",
		ExtAuthzServiceName:      os.Getenv(envExtAuthzName),
		ExtAuthzServiceNamespace: os.Getenv(envExtAuthzNamespace),
		ExtAuthzServicePort:      getEnvIntOrDefault(envExtAuthzPort, defaultExtAuthzPort),
		DefaultAction:            getEnvOrDefault(envDefaultAction, defaultDefaultAction),
	}
}

// IsOperational reports whether authorization is enabled and the external
// authorization backend is fully specified. The operator should only generate
// authorization policies when this returns true.
func (c Config) IsOperational() bool {
	return c.Enabled && c.ExtAuthzServiceName != "" && c.ExtAuthzServiceNamespace != "" && c.ExtAuthzServicePort > 0
}

// ExtAuthzServiceHost returns the fully-qualified in-cluster DNS name of the
// external authorization Service.
func (c Config) ExtAuthzServiceHost() string {
	return fmt.Sprintf("%s.%s.svc.cluster.local", c.ExtAuthzServiceName, c.ExtAuthzServiceNamespace)
}

func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvIntOrDefault(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			return parsed
		}
	}
	return defaultValue
}
