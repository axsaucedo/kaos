package util

import (
	corev1 "k8s.io/api/core/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// BuildTelemetryEnvVars creates environment variables for OpenTelemetry configuration.
// Uses standard OTEL_* env vars so the SDK auto-configures.
// serviceName is used as OTEL_SERVICE_NAME (typically the CR name).
// namespace is added to OTEL_RESOURCE_ATTRIBUTES.
func BuildTelemetryEnvVars(tel *kaosv1alpha1.TelemetryConfig, serviceName, namespace string) []corev1.EnvVar {
	if tel == nil || !tel.Enabled {
		return nil
	}

	envVars := []corev1.EnvVar{
		{
			Name:  "OTEL_ENABLED",
			Value: "true",
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

	// Add resource attributes for Kubernetes context
	resourceAttrs := "service.namespace=" + namespace + ",kaos.resource.name=" + serviceName
	envVars = append(envVars, corev1.EnvVar{
		Name:  "OTEL_RESOURCE_ATTRIBUTES",
		Value: resourceAttrs,
	})

	return envVars
}
