# OpenTelemetry Implementation Report

## Summary

This report documents the comprehensive fixes and enhancements to the KAOS OpenTelemetry implementation across both the Python data plane and Go control plane.

## Bug Fixes Completed

### 1. ContextVar Mutable Default Bug (CRITICAL)

**Problem**: The `_span_stack` ContextVar was initialized with `default=[]`, which creates a shared mutable object across all async contexts. This could lead to span stack corruption when multiple requests run concurrently.

**Fix**: Changed default to `None` and allocate per-context:
```python
_span_stack: ContextVar[Optional[List[SpanState]]] = ContextVar("kaos_span_stack", default=None)

def _get_stack(self) -> List[SpanState]:
    stack = _span_stack.get()
    if stack is None:
        stack = []
        _span_stack.set(stack)
    return stack
```

**Files Modified**: `python/telemetry/manager.py`

### 2. Span Ending Pattern (except/finally → except/else)

**Problem**: Using `span_success()` in `finally` block runs after exception is re-raised, which is semantically wrong even though no-op guards prevent double-ending.

**Fix**: Changed pattern to use `else` block for success:
```python
self._otel.span_begin(...)
try:
    result = ...
except Exception as e:
    self._otel.span_failure(e)
    raise
else:
    self._otel.span_success()
    return result
```

**Files Modified**: `python/agent/client.py`

### 3. otel_enabled Computed Before init_otel()

**Problem**: `is_otel_enabled()` returns `_initialized` which is `False` before `init_otel()` is called, so logging correlation wasn't being enabled at startup.

**Fix**: Added `should_enable_otel()` function that checks environment variables directly:
```python
def should_enable_otel() -> bool:
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() in ("true", "1", "yes")
    has_service_name = bool(os.getenv("OTEL_SERVICE_NAME"))
    has_endpoint = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    return not disabled and has_service_name and has_endpoint
```

**Files Modified**: `python/telemetry/manager.py`, `python/agent/server.py`

### 4. OTEL_RESOURCE_ATTRIBUTES Reading Operator's Env

**Problem**: `BuildTelemetryEnvVars` used `os.Getenv("OTEL_RESOURCE_ATTRIBUTES")` which reads the operator pod's environment, not the target workload's CR env.

**Fix**: Removed `os.Getenv()` and set KAOS attributes directly. User values in `spec.config.env` take precedence when they appear later in the env list.

**Files Modified**: `operator/pkg/util/telemetry.go`

### 5. Exporter TLS/Insecure Behavior

**Problem**: Explicitly passing `endpoint=...` to `OTLPSpanExporter` could bypass environment-based configuration for TLS settings.

**Fix**: Let `OTLPSpanExporter()` use environment variables for endpoint configuration so that `OTEL_EXPORTER_OTLP_INSECURE` and other advanced settings work correctly.

**Files Modified**: `python/telemetry/manager.py`

### 6. Docs/CRD Endpoint Default Mismatch

**Problem**: CRD had a default endpoint value (`http://localhost:4317`) but docs said endpoint is required when enabled.

**Fix**: Removed default from CRD so endpoint is truly required. Updated `make generate manifests`.

**Files Modified**: `operator/api/v1alpha1/agent_types.go`

### 7. MCPServer _otel_enabled Test Semantics

**Problem**: Tests claimed MCPServer is "enabled by default" but `_otel_enabled=True` means "not disabled", not "fully configured and active".

**Fix**: Clarified test names and docstrings to reflect actual semantics.

**Files Modified**: `python/tests/test_telemetry.py`

### 8. ModelAPI CRD Telemetry Extension

**Problem**: ModelAPI CRD didn't support telemetry configuration.

**Fix**: 
- Added `Telemetry *TelemetryConfig` field to `ModelAPISpec`
- For LiteLLM Proxy mode: 
  - Generate config with `success_callback: ["otel"]` and `failure_callback: ["otel"]`
  - Set `OTEL_EXPORTER=otlp`, `OTEL_ENDPOINT`, `OTEL_SERVICE_NAME` env vars
- For Ollama Hosted mode:
  - Emit warning: "OpenTelemetry telemetry is not supported for Ollama (Hosted mode)"

**Files Modified**: `operator/api/v1alpha1/modelapi_types.go`, `operator/controllers/modelapi_controller.go`, `docs/operator/telemetry.md`

## Manual Validation Results

### Test Setup
- Deployed OpenTelemetry Collector in `monitoring` namespace with debug exporter
- Created test resources in `otel-validation` namespace:
  - ModelAPI (Proxy mode) with telemetry enabled
  - MCPServer with telemetry enabled
  - Agent with telemetry enabled

### Verification Results

#### ✅ Environment Variables
All resources correctly received OTel environment variables:
```
OTEL_SDK_DISABLED=false
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4317
OTEL_SERVICE_NAME=<resource-name>
OTEL_RESOURCE_ATTRIBUTES=service.namespace=otel-validation,kaos.resource.name=<resource-name>
```

#### ✅ Initialization Logs
Agent logs show successful OTel initialization:
```
telemetry.manager - INFO - OpenTelemetry initialized: http://otel-collector.monitoring.svc.cluster.local:4317 (service: test-agent)
agent.server - INFO - OpenTelemetry instrumentation enabled (FastAPI + HTTPX)
```

#### ✅ Trace Context Propagation
Same trace ID propagates from Agent to MCPServer:
```
# Agent logs
mcp.client.streamable_http - INFO - [trace_id=2c7e1777b629adf3162a5d7d281b1afc span_id=ad3d87815fcf8613] - Received session ID...

# MCPServer logs  
mcp.server.streamable_http_manager - INFO - [trace_id=2c7e1777b629adf3162a5d7d281b1afc span_id=0607d56ff716aee5] - Created new transport...
```

#### ✅ Log Correlation
All log entries include trace context when within a traced request:
```
2026-01-26 20:01:24 - modelapi.client - ERROR - [trace_id=2c7e1777b629adf3162a5d7d281b1afc span_id=793a53477df4024c] - HTTP error...
```

#### ✅ Spans Exported
OTel Collector received spans with correct attributes:
```
Resource attributes:
  -> telemetry.sdk.language: Str(python)
  -> telemetry.sdk.name: Str(opentelemetry)
  -> service.namespace: Str(otel-validation)
  -> kaos.resource.name: Str(test-agent)
  -> service.name: Str(test-agent)

Span:
  Trace ID: 2c7e1777b629adf3162a5d7d281b1afc
  Name: GET /mcp
  Kind: Server
```

#### ✅ LiteLLM Configuration
ModelAPI Proxy correctly generates LiteLLM config with OTel callbacks:
```yaml
litellm_settings:
  success_callback: ["otel"]
  failure_callback: ["otel"]
```

#### ✅ Ollama Warning
Operator correctly emits warning for Hosted mode:
```
WARNING: OpenTelemetry telemetry is not supported for Ollama (Hosted mode). Traces and metrics will not be collected.
```

## Architecture Overview

### CRD Configuration
Minimal CRD fields (advanced settings via standard `OTEL_*` env vars):
- `telemetry.enabled`: Enable/disable OpenTelemetry
- `telemetry.endpoint`: OTLP gRPC endpoint (required when enabled)

### Operator-Set Environment Variables
| Variable | Description |
|----------|-------------|
| `OTEL_SDK_DISABLED` | "false" when enabled (standard OTel env var) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | From `telemetry.endpoint` |
| `OTEL_SERVICE_NAME` | CR name |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.namespace`, `kaos.resource.name` |

### Python Telemetry Manager
- Inline span API: `span_begin()`, `span_success()`, `span_failure()`
- ContextVar-based span stack for async safety
- Auto-instrumentation: FastAPI, HTTPX, logging correlation

### Span Hierarchy
```
HTTP POST /v1/chat/completions (SERVER, auto-instrumented)
└── agent.agentic_loop (INTERNAL)
    ├── agent.step.1 (INTERNAL)
    │   └── model.inference (CLIENT)
    ├── agent.step.2 (INTERNAL)
    │   ├── model.inference (CLIENT)
    │   └── tool.calculator (CLIENT)
    └── agent.step.3 (INTERNAL)
        └── delegate.researcher (CLIENT)
```

## Bug Fixes Round 2 (Additional Fixes)

### 1. Python Span Leakage in Success Paths

**Problem**: Using `try/except/else` with `return`/`yield` inside `try` block bypasses the `else` block, leaving spans open and context attached.

**Fix**: Changed to `try/except/finally` with `failed` flag:
```python
self._otel.span_begin(...)
failed = False
try:
    ...
except Exception as e:
    failed = True
    self._otel.span_failure(e)
    raise
finally:
    if not failed:
        self._otel.span_success()
```

**Files Modified**: `python/agent/client.py`

### 2. MCPServer Treating "Not Disabled" as "Enabled"

**Problem**: MCPServer checked only `OTEL_SDK_DISABLED`, not whether required env vars exist. This caused instrumentation to run without a valid backend.

**Fix**: Changed to use `should_enable_otel()` from telemetry.manager which checks all required env vars.

**Files Modified**: `python/mcptools/server.py`, `python/tests/test_telemetry.py`

### 3. LiteLLM OTel Env Var Names

**Problem**: Operator set `OTEL_ENDPOINT` but standard is `OTEL_EXPORTER_OTLP_ENDPOINT`.

**Fix**: Changed to use standard env var name. Documented that custom `proxyConfig.configYaml.fromString` requires manual callback setup.

**Files Modified**: `operator/controllers/modelapi_controller.go`, `docs/operator/telemetry.md`

### 4. TelemetryConfig Merge (Field-Wise)

**Problem**: `MergeTelemetryConfig()` returned component OR global config, not merged fields. Users couldn't set enabled at component level while inheriting global endpoint.

**Fix**: Implemented field-wise merge:
- If component sets enabled but no endpoint, inherit global endpoint
- Added `IsTelemetryConfigValid()` validation function
- Controllers emit warning when enabled=true but endpoint empty

**Files Modified**: `operator/pkg/util/telemetry.go`, `operator/controllers/agent_controller.go`, `operator/controllers/mcpserver_controller.go`, `operator/controllers/modelapi_controller.go`

### 5. CRD Endpoint Defaults Inconsistency

**Problem**: Helm CRDs had `endpoint: default: http://localhost:4317` which silently blackholes telemetry in-cluster.

**Fix**: Removed default. Endpoint is now required when enabled (validated by controllers).

**Files Modified**: `operator/chart/crds/*.yaml`

### 6. Metric Names/Labels in Docs

**Problem**: Docs said `kaos.agent.requests`, code emits `kaos.requests`. Docs said seconds, code uses milliseconds.

**Fix**: Updated docs to match actual implementation:
- Metrics: `kaos.requests`, `kaos.request.duration`, `kaos.tool.duration`, etc.
- Labels: `success: "true"/"false"` (not `status`)
- Duration: milliseconds

**Files Modified**: `docs/operator/telemetry.md`

### 7. SpanState Token Type Annotation

**Problem**: Type checker error - `SpanState.token` typed as `object` but needs `Token[Context]`.

**Fix**: Added proper type annotation with necessary imports.

**Files Modified**: `python/telemetry/manager.py`

### 8. Helm values.yaml Regeneration

**Problem**: `make helm` overwrites values.yaml, removing custom values for defaultImages, gatewayAPI, gateway.defaultTimeouts, and telemetry.

**Fix**: Restored all required values after CRD regeneration.

**Files Modified**: `operator/chart/values.yaml`

## Log Level Configuration (Round 3)

### Overview
Added centralized log level configuration to KAOS that applies to both control plane (operator) and data plane (Agent, MCPServer, ModelAPI) components.

### Changes Made

#### 1. Helm Chart Configuration
Added `logLevel` parameter to `values.yaml`:
```yaml
logLevel: INFO  # TRACE, DEBUG, INFO, WARNING, ERROR
```

The operator reads this as `DEFAULT_LOG_LEVEL` environment variable.

**Files Modified**: `operator/chart/values.yaml`, `operator/chart/templates/operator-configmap.yaml`

#### 2. Python LOG_LEVEL Standardization
Standardized on `LOG_LEVEL` environment variable across all Python components:
- Agent: `LOG_LEVEL` (fallback: `AGENT_LOG_LEVEL`)
- MCPServer: `LOG_LEVEL` (fallback: `MCP_LOG_LEVEL`)

**Files Modified**: `python/agent/server.py`, `python/mcptools/server.py`

#### 3. Operator LOG_LEVEL Propagation
Updated all controllers to pass `LOG_LEVEL` to data plane pods:
- `util.GetDefaultLogLevel()` - Gets default from `DEFAULT_LOG_LEVEL` env var
- `util.BuildLogLevelEnvVar()` - Builds LOG_LEVEL env var if not set by user

**Files Modified**: `operator/pkg/util/telemetry.go`, `operator/controllers/agent_controller.go`, `operator/controllers/mcpserver_controller.go`

#### 4. LiteLLM and Ollama Log Level Mapping
Added log level mapping for external components:
- **LiteLLM**: Maps `LOG_LEVEL` to `LITELLM_LOG` (TRACE→DEBUG, DEBUG→DEBUG, INFO→INFO, etc.)
- **Ollama**: Maps `LOG_LEVEL` to `OLLAMA_DEBUG` (TRACE→2, DEBUG→1, INFO/WARNING/ERROR→0)

**Files Modified**: `operator/controllers/modelapi_controller.go`

#### 5. Comprehensive Debug Logging
Added debug logging throughout the Python codebase:
- **Startup config**: OTEL endpoint, service name, resource attributes, log level
- **Model calls**: Message count, response length, failures
- **Tool execution**: Tool name, argument keys, success/failure
- **Delegation**: Target agent, task length, result length

**Files Modified**: `python/agent/server.py`, `python/mcptools/server.py`, `python/agent/client.py`

#### 6. Trace Context in Memory Events
Memory events now automatically include trace context when OTel is enabled:
```python
# Added to LocalMemory.create_event()
if is_otel_enabled():
    trace_ctx = get_current_trace_context()  # Returns trace_id, span_id
    event_metadata.update(trace_ctx)
```

Enables querying events by trace_id for debugging agent workflows.

**Files Modified**: `python/agent/memory.py`, `python/telemetry/manager.py`

### Log Level Mapping Summary

| KAOS Level | Python | LiteLLM | Ollama |
|------------|--------|---------|--------|
| TRACE | DEBUG | DEBUG | OLLAMA_DEBUG=2 |
| DEBUG | DEBUG | DEBUG | OLLAMA_DEBUG=1 |
| INFO | INFO | INFO | (default) |
| WARNING | WARNING | WARNING | (default) |
| ERROR | ERROR | ERROR | (default) |

## CI Status
- All tests passing (Python, Go unit tests, E2E)
- Final commit: 3dde9b7

## Files Changed

### Python
- `python/telemetry/manager.py` - Core OTel implementation with trace context getter
- `python/agent/client.py` - Agent with debug logging for model/tool/delegation
- `python/agent/server.py` - Server with LOG_LEVEL support and OTEL startup logging
- `python/agent/memory.py` - Memory events with trace context correlation
- `python/mcptools/server.py` - MCPServer with LOG_LEVEL support and OTEL logging
- `python/tests/test_telemetry.py` - Updated tests

### Go Operator
- `operator/api/v1alpha1/agent_types.go` - Removed endpoint default
- `operator/api/v1alpha1/modelapi_types.go` - Added Telemetry field
- `operator/controllers/agent_controller.go` - LOG_LEVEL propagation
- `operator/controllers/mcpserver_controller.go` - LOG_LEVEL propagation
- `operator/controllers/modelapi_controller.go` - LiteLLM/Ollama log level mapping
- `operator/pkg/util/telemetry.go` - Log level utilities

### Helm Chart
- `operator/chart/values.yaml` - Added logLevel parameter
- `operator/chart/templates/operator-configmap.yaml` - DEFAULT_LOG_LEVEL env var

### Documentation
- `docs/operator/telemetry.md` - Updated with ModelAPI telemetry, corrected env var descriptions

