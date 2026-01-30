"""
OpenTelemetry instrumentation for KAOS.

Uses standard OTEL_* environment variables. When OTEL_SDK_DISABLED is not set or "false",
traces, metrics, and log correlation are enabled (if endpoint is configured).
"""
