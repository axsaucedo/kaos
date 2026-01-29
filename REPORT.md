# OTEL Logging Configuration

## Overview

This document describes the OpenTelemetry logging configuration options for KAOS data plane components (Agent, MCPServer).

## Distributed Tracing

KAOS implements **manual trace context propagation** across agent delegations:

- **Outgoing requests** (RemoteAgent): Automatically injects `traceparent`/`tracestate` headers
- **Incoming requests** (AgentServer): Automatically extracts trace context from headers

This ensures traces are connected across agent-to-agent delegations **without** requiring HTTPX/FastAPI auto-instrumentation, avoiding noisy HTTP spans.

## Environment Variables

### Log Level

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level for all components (TRACE, DEBUG, INFO, WARNING, ERROR) |
| `AGENT_LOG_LEVEL` | - | Fallback for LOG_LEVEL (backwards compatibility) |

The log level controls:
- Python logging output to stdout
- OTEL log export level (DEBUG logs only exported when LOG_LEVEL=DEBUG)

### HTTP Tracing Options

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_INCLUDE_HTTP_CLIENT` | `false` | Enable HTTPX client span tracing and logging |
| `OTEL_INCLUDE_HTTP_SERVER` | `false` | Enable FastAPI span tracing and uvicorn access logs |

#### OTEL_INCLUDE_HTTP_CLIENT

When **disabled** (default):
- HTTPX client calls do NOT create trace spans
- Trace context is still propagated via headers (manual injection)
- `httpx`, `httpcore`, `mcp.client.streamable_http` loggers set to WARNING
- Reduces noise from MCP SSE connections which create many HTTP calls

When **enabled** (`true`):
- All HTTPX client calls create trace spans (noisy)
- HTTP client loggers use configured LOG_LEVEL
- Useful for debugging network issues

#### OTEL_INCLUDE_HTTP_SERVER

When **disabled** (default):
- FastAPI incoming requests do NOT create HTTP spans
- Trace context is still extracted from headers (manual extraction)
- Uvicorn access logs are suppressed (no "GET /health 200" messages)
- Reduces noise from Kubernetes health/readiness probes

When **enabled** (`true`):
- FastAPI incoming requests create trace spans (noisy)
- Uvicorn access logs are emitted at configured LOG_LEVEL
- Useful for debugging incoming request issues

## Log Record Attributes

OTEL log exports include these attributes:

| Attribute | Description |
|-----------|-------------|
| `logger_name` | Python logger name (e.g., `agent.client`, `mcptools.server`) |
| `code.filepath` | Source file path |
| `code.function` | Function name |
| `code.lineno` | Line number |

## Log/Span Correlation

When OTEL is enabled, all log entries within a traced request include:
- `trace_id` - correlates with the request trace
- `span_id` - correlates with the active span

**Important:** Logs must be emitted BEFORE `span_failure()` or AFTER `span_begin()` to include trace correlation.

## Configuration Examples

### Minimal OTEL (default)

```bash
# Connected agent traces, no HTTP noise
LOG_LEVEL=INFO
OTEL_SDK_DISABLED=false
OTEL_SERVICE_NAME=my-agent
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317
```

### Debug with full HTTP tracing

```bash
# Full visibility for debugging (noisy)
LOG_LEVEL=DEBUG
OTEL_INCLUDE_HTTP_CLIENT=true
OTEL_INCLUDE_HTTP_SERVER=true
```

### Production recommended

```bash
# Connected traces, errors visible, minimal noise
LOG_LEVEL=INFO
OTEL_INCLUDE_HTTP_CLIENT=false
OTEL_INCLUDE_HTTP_SERVER=false
```

## Helper Functions

The `telemetry.manager` module exports:

- `get_log_level()` - Get LOG_LEVEL as string
- `get_log_level_int()` - Get LOG_LEVEL as logging constant
- `getenv_bool(name, default)` - Parse boolean env var ("true"/"1"/"yes")
