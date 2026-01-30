package util

import (
	"os"

	corev1 "k8s.io/api/core/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// GetDefaultTelemetryConfig returns a TelemetryConfig from global environment variables.
// Returns nil if DEFAULT_TELEMETRY_ENABLED is not "true".
func GetDefaultTelemetryConfig() *kaosv1alpha1.TelemetryConfig {
	if os.Getenv("DEFAULT_TELEMETRY_ENABLED") != "true" {
		return nil
	}
	return &kaosv1alpha1.TelemetryConfig{
		Enabled:  true,
		Endpoint: os.Getenv("DEFAULT_TELEMETRY_ENDPOINT"),
	}
}

// MergeTelemetryConfig performs field-wise merge of component-level telemetry config
// with global defaults. Component-level fields take precedence when set.
// This allows a component to set enabled=true and inherit the global endpoint.
func MergeTelemetryConfig(componentConfig *kaosv1alpha1.TelemetryConfig) *kaosv1alpha1.TelemetryConfig {
	globalConfig := GetDefaultTelemetryConfig()

	// If no component config, use global (may be nil)
	if componentConfig == nil {
		return globalConfig
	}

	// If no global config, use component as-is
	if globalConfig == nil {
		return componentConfig
	}

	// Field-wise merge: component fields take precedence if set
	merged := &kaosv1alpha1.TelemetryConfig{
		Enabled: componentConfig.Enabled, // Component controls enabled state
	}

	// Endpoint: use component if set, otherwise inherit global
	if componentConfig.Endpoint != "" {
		merged.Endpoint = componentConfig.Endpoint
	} else {
		merged.Endpoint = globalConfig.Endpoint
	}

	return merged
}

// IsTelemetryConfigValid returns true if the telemetry config is valid.
// A valid config has enabled=true and non-empty endpoint.
func IsTelemetryConfigValid(tel *kaosv1alpha1.TelemetryConfig) bool {
	if tel == nil || !tel.Enabled {
		return true // disabled is valid (just means no telemetry)
	}
	return tel.Endpoint != ""
}

// BuildTelemetryEnvVars creates environment variables for OpenTelemetry configuration.
// Uses standard OTEL_* env vars so the SDK auto-configures.
// serviceName is used as OTEL_SERVICE_NAME (typically the CR name).
// namespace is added to OTEL_RESOURCE_ATTRIBUTES as KAOS-specific attributes.
// Note: If user sets OTEL_RESOURCE_ATTRIBUTES in spec.config.env, both will be present
// and the user value takes precedence when they appear later in the env list.
func BuildTelemetryEnvVars(tel *kaosv1alpha1.TelemetryConfig, serviceName, namespace string) []corev1.EnvVar {
	if tel == nil || !tel.Enabled {
		return nil
	}

	envVars := []corev1.EnvVar{
		{
			Name:  "OTEL_SDK_DISABLED",
			Value: "false",
		},
		{
			Name:  "OTEL_SERVICE_NAME",
			Value: serviceName,
		},
	}

	if tel.Endpoint != "" {
		envVars = append(envVars, corev1.EnvVar{
			Name:  "OTEL_EXPORTER_OTLP_ENDPOINT",
			Value: tel.Endpoint,
		})
	}

	// Add KAOS-specific resource attributes
	// These are added as a baseline; if user also sets OTEL_RESOURCE_ATTRIBUTES
	// in spec.config.env, the container runtime merges them (later values win)
	kaosAttrs := "service.namespace=" + namespace + ",kaos.resource.name=" + serviceName
	envVars = append(envVars, corev1.EnvVar{
		Name:  "OTEL_RESOURCE_ATTRIBUTES",
		Value: kaosAttrs,
	})

	// Exclude health check endpoints from FastAPI instrumentation traces
	// Reduces noise from Kubernetes liveness/readiness probes
	// Uses simple patterns that match anywhere in URL path (search, not match)
	envVars = append(envVars, corev1.EnvVar{
		Name:  "OTEL_PYTHON_FASTAPI_EXCLUDED_URLS",
		Value: "/health,/ready",
	})

	return envVars
}

// GetDefaultLogLevel returns the default log level from the DEFAULT_LOG_LEVEL env var.
// Falls back to "INFO" if not set.
func GetDefaultLogLevel() string {
	level := os.Getenv("DEFAULT_LOG_LEVEL")
	if level == "" {
		return "INFO"
	}
	return level
}

// BuildLogLevelEnvVar creates the LOG_LEVEL env var if not already in the provided list.
// Returns a slice with the LOG_LEVEL env var, or empty if already present.
func BuildLogLevelEnvVar(existingEnv []corev1.EnvVar) []corev1.EnvVar {
	// Check if LOG_LEVEL is already set
	for _, e := range existingEnv {
		if e.Name == "LOG_LEVEL" {
			return nil // Already set by user
		}
	}
	return []corev1.EnvVar{
		{
			Name:  "LOG_LEVEL",
			Value: GetDefaultLogLevel(),
		},
	}
}
