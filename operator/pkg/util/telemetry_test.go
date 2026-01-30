package util

import (
	"os"
	"testing"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestGetDefaultTelemetryConfig(t *testing.T) {
	tests := []struct {
		name           string
		envEnabled     string
		envEndpoint    string
		expectNil      bool
		expectEnabled  bool
		expectEndpoint string
	}{
		{
			name:      "disabled when env not set",
			expectNil: true,
		},
		{
			name:       "disabled when env is false",
			envEnabled: "false",
			expectNil:  true,
		},
		{
			name:           "enabled when env is true",
			envEnabled:     "true",
			envEndpoint:    "http://collector:4317",
			expectNil:      false,
			expectEnabled:  true,
			expectEndpoint: "http://collector:4317",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clear env
			os.Unsetenv("DEFAULT_TELEMETRY_ENABLED")
			os.Unsetenv("DEFAULT_TELEMETRY_ENDPOINT")

			// Set env for test
			if tt.envEnabled != "" {
				os.Setenv("DEFAULT_TELEMETRY_ENABLED", tt.envEnabled)
			}
			if tt.envEndpoint != "" {
				os.Setenv("DEFAULT_TELEMETRY_ENDPOINT", tt.envEndpoint)
			}

			result := GetDefaultTelemetryConfig()

			if tt.expectNil && result != nil {
				t.Errorf("expected nil, got %+v", result)
			}
			if !tt.expectNil {
				if result == nil {
					t.Fatal("expected non-nil result")
				}
				if result.Enabled != tt.expectEnabled {
					t.Errorf("expected Enabled=%v, got %v", tt.expectEnabled, result.Enabled)
				}
				if result.Endpoint != tt.expectEndpoint {
					t.Errorf("expected Endpoint=%s, got %s", tt.expectEndpoint, result.Endpoint)
				}
			}
		})
	}
}

func TestMergeTelemetryConfig(t *testing.T) {
	// Set up global defaults
	os.Setenv("DEFAULT_TELEMETRY_ENABLED", "true")
	os.Setenv("DEFAULT_TELEMETRY_ENDPOINT", "http://global:4317")
	defer func() {
		os.Unsetenv("DEFAULT_TELEMETRY_ENABLED")
		os.Unsetenv("DEFAULT_TELEMETRY_ENDPOINT")
	}()

	tests := []struct {
		name            string
		componentConfig *kaosv1alpha1.TelemetryConfig
		expectEnabled   bool
		expectEndpoint  string
	}{
		{
			name:            "uses global when component is nil",
			componentConfig: nil,
			expectEnabled:   true,
			expectEndpoint:  "http://global:4317",
		},
		{
			name: "uses component when specified",
			componentConfig: &kaosv1alpha1.TelemetryConfig{
				Enabled:  true,
				Endpoint: "http://component:4317",
			},
			expectEnabled:  true,
			expectEndpoint: "http://component:4317",
		},
		{
			name: "component can disable telemetry",
			componentConfig: &kaosv1alpha1.TelemetryConfig{
				Enabled: false,
			},
			expectEnabled:  false,
			expectEndpoint: "http://global:4317", // inherits global endpoint
		},
		{
			name: "inherits global endpoint when component sets enabled but no endpoint",
			componentConfig: &kaosv1alpha1.TelemetryConfig{
				Enabled: true,
				// Endpoint not set
			},
			expectEnabled:  true,
			expectEndpoint: "http://global:4317", // inherited from global
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := MergeTelemetryConfig(tt.componentConfig)

			if result == nil {
				t.Fatal("expected non-nil result")
			}
			if result.Enabled != tt.expectEnabled {
				t.Errorf("expected Enabled=%v, got %v", tt.expectEnabled, result.Enabled)
			}
			if tt.expectEndpoint != "" && result.Endpoint != tt.expectEndpoint {
				t.Errorf("expected Endpoint=%s, got %s", tt.expectEndpoint, result.Endpoint)
			}
		})
	}
}

func TestIsTelemetryConfigValid(t *testing.T) {
	tests := []struct {
		name   string
		tel    *kaosv1alpha1.TelemetryConfig
		expect bool
	}{
		{
			name:   "nil is valid",
			tel:    nil,
			expect: true,
		},
		{
			name:   "disabled is valid",
			tel:    &kaosv1alpha1.TelemetryConfig{Enabled: false},
			expect: true,
		},
		{
			name: "enabled with endpoint is valid",
			tel: &kaosv1alpha1.TelemetryConfig{
				Enabled:  true,
				Endpoint: "http://collector:4317",
			},
			expect: true,
		},
		{
			name: "enabled without endpoint is invalid",
			tel: &kaosv1alpha1.TelemetryConfig{
				Enabled:  true,
				Endpoint: "",
			},
			expect: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := IsTelemetryConfigValid(tt.tel)
			if result != tt.expect {
				t.Errorf("expected %v, got %v", tt.expect, result)
			}
		})
	}
}

func TestBuildTelemetryEnvVars(t *testing.T) {
	// Clear any existing env
	os.Unsetenv("OTEL_RESOURCE_ATTRIBUTES")

	tests := []struct {
		name        string
		tel         *kaosv1alpha1.TelemetryConfig
		serviceName string
		namespace   string
		expectCount int
		expectOTEL  bool
	}{
		{
			name:        "nil config returns empty",
			tel:         nil,
			expectCount: 0,
		},
		{
			name:        "disabled config returns empty",
			tel:         &kaosv1alpha1.TelemetryConfig{Enabled: false},
			expectCount: 0,
		},
		{
			name: "enabled config returns env vars",
			tel: &kaosv1alpha1.TelemetryConfig{
				Enabled:  true,
				Endpoint: "http://collector:4317",
			},
			serviceName: "test-agent",
			namespace:   "default",
			expectCount: 5, // OTEL_SDK_DISABLED, OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_RESOURCE_ATTRIBUTES, OTEL_PYTHON_FASTAPI_EXCLUDED_URLS
			expectOTEL:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := BuildTelemetryEnvVars(tt.tel, tt.serviceName, tt.namespace)

			if len(result) != tt.expectCount {
				t.Errorf("expected %d env vars, got %d", tt.expectCount, len(result))
			}

			if tt.expectOTEL {
				hasSDKDisabled := false
				hasServiceName := false
				hasExcludedURLs := false
				for _, env := range result {
					if env.Name == "OTEL_SDK_DISABLED" && env.Value == "false" {
						hasSDKDisabled = true
					}
					if env.Name == "OTEL_SERVICE_NAME" && env.Value == tt.serviceName {
						hasServiceName = true
					}
					if env.Name == "OTEL_PYTHON_FASTAPI_EXCLUDED_URLS" && env.Value == "/health,/ready" {
						hasExcludedURLs = true
					}
				}
				if !hasSDKDisabled {
					t.Error("expected OTEL_SDK_DISABLED=false")
				}
				if !hasServiceName {
					t.Errorf("expected OTEL_SERVICE_NAME=%s", tt.serviceName)
				}
				if !hasExcludedURLs {
					t.Error("expected OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=/health,/ready")
				}
			}
		})
	}
}
