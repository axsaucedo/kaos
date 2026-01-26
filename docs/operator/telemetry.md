# OpenTelemetry

KAOS supports OpenTelemetry for observability, including distributed tracing, metrics, and log correlation across all agent and MCP server operations.

## Overview

When enabled, OpenTelemetry instrumentation provides:

- **Tracing**: Distributed traces across agent requests, model calls, tool executions, and delegations
- **Metrics**: Counters and histograms for requests, latency, and error rates
- **Log Correlation**: Automatic injection of trace_id and span_id into log entries

## Global Telemetry Configuration

You can enable telemetry globally for all components via Helm values:

```yaml
# values.yaml
telemetry:
  enabled: true
  endpoint: "http://otel-collector.observability.svc.cluster.local:4317"
```

Install with global telemetry enabled:

```bash
helm install kaos oci://ghcr.io/axsaucedo/kaos/chart \
  --namespace kaos-system \
  --set telemetry.enabled=true \
  --set telemetry.endpoint="http://otel-collector:4317"
```

All Agents and MCPServers will have telemetry enabled by default with this configuration.

## Component-Level Configuration

Override global defaults or enable telemetry for specific components:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
spec:
  modelAPI: my-modelapi
  model: "openai/gpt-4o"
  config:
    description: "Agent with OpenTelemetry enabled"
    telemetry:
      enabled: true
      endpoint: "http://otel-collector.monitoring.svc.cluster.local:4317"
```

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: my-tools
spec:
  type: python-runtime
  config:
    telemetry:
      enabled: true
      endpoint: "http://otel-collector.monitoring.svc.cluster.local:4317"
    tools:
      fromString: |
        def echo(msg: str) -> str:
            return msg
```

### Configuration Precedence

Component-level configuration always overrides global defaults:

1. **Component-level telemetry** (highest priority): If `spec.config.telemetry` is set on the Agent or MCPServer, or `spec.telemetry` on ModelAPI, it is used
2. **Global Helm values** (default): If component-level telemetry is not set, the global `telemetry.enabled` and `telemetry.endpoint` values are used

## Configuration Fields

The CRD configuration is intentionally minimal. For advanced settings, use standard `OTEL_*` environment variables via `spec.config.env`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable OpenTelemetry instrumentation |
| `endpoint` | string | - | OTLP exporter endpoint (gRPC, required when enabled) |

### Advanced Configuration via Environment Variables

For advanced configuration, use the standard [OpenTelemetry environment variables](https://opentelemetry-python.readthedocs.io/en/latest/sdk/environment_variables.html):

```yaml
spec:
  config:
    telemetry:
      enabled: true
      endpoint: "http://otel-collector:4317"
    env:
    - name: OTEL_EXPORTER_OTLP_INSECURE
      value: "false"  # Use TLS
    - name: OTEL_EXPORTER_OTLP_HEADERS
      value: "x-api-key=YOUR_KEY"
    - name: OTEL_TRACES_SAMPLER
      value: "parentbased_traceidratio"
    - name: OTEL_TRACES_SAMPLER_ARG
      value: "0.1"  # Sample 10% of traces
    - name: OTEL_RESOURCE_ATTRIBUTES
      value: "deployment.environment=production"
```

The operator automatically sets:
- `OTEL_SDK_DISABLED`: Set to "false" when telemetry is enabled (standard OTel env var)
- `OTEL_SERVICE_NAME`: Defaults to the CR name (e.g., agent name)
- `OTEL_EXPORTER_OTLP_ENDPOINT`: From `telemetry.endpoint`
- `OTEL_RESOURCE_ATTRIBUTES`: Sets `service.namespace` and `kaos.resource.name`

## ModelAPI Telemetry

ModelAPI supports telemetry for the LiteLLM Proxy mode. For Ollama Hosted mode, telemetry is not supported (Ollama has no native OTel support).

### LiteLLM Proxy Mode

When `spec.telemetry.enabled: true` on a Proxy-mode ModelAPI:
- LiteLLM config is automatically updated with `success_callback: ["otel"]` and `failure_callback: ["otel"]`
- Environment variables `OTEL_EXPORTER`, `OTEL_ENDPOINT`, and `OTEL_SERVICE_NAME` are set
- LiteLLM will send traces for each model call to the configured OTLP endpoint

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: my-modelapi
spec:
  mode: Proxy
  telemetry:
    enabled: true
    endpoint: "http://otel-collector:4317"
  proxyConfig:
    models: ["*"]
    provider: "openai"
    apiBase: "https://api.openai.com/v1"
```

### Ollama Hosted Mode

If telemetry is enabled for a Hosted-mode ModelAPI, the operator emits a warning in the status message. Ollama does not have native OpenTelemetry support, so traces and metrics will not be collected from the model server itself.

## Trace Spans

The following spans are automatically created:

### HTTP Request (auto-instrumented)

FastAPI/Starlette auto-instrumentation creates the root SERVER span for each HTTP request. This provides standard HTTP attributes like `http.method`, `http.url`, `http.status_code`.

### agent.agentic_loop

Main processing span for agent reasoning. Attributes:
- `agent.name`: Name of the agent
- `session.id`: Session identifier
- `agent.max_steps`: Maximum reasoning steps
- `stream`: Whether streaming is enabled

### agent.step.{n}

Span for each iteration of the agentic reasoning loop. Attributes:
- `step`: Step number (1-based)
- `max_steps`: Maximum allowed steps

### model.inference

Span for LLM API calls. Attributes:
- `gen_ai.request.model`: Model identifier

### tool.{name}

Span for MCP tool executions. Attributes:
- `tool.name`: Tool name

### delegate.{agent}

Span for agent-to-agent delegations. Attributes:
- `agent.delegation.target`: Target agent name

## Span Hierarchy Example

```
HTTP POST /v1/chat/completions (SERVER, auto-instrumented)
└── agent.agentic_loop (INTERNAL)
    ├── agent.step.1 (INTERNAL)
    │   └── model.inference (CLIENT)
    ├── agent.step.2 (INTERNAL)
    │   ├── model.inference (CLIENT)
    │   └── tool.calculator (CLIENT)
    ├── agent.step.3 (INTERNAL)
    │   ├── model.inference (CLIENT)
    │   └── delegate.researcher (CLIENT)
    └── agent.step.4 (INTERNAL)
        └── model.inference (CLIENT)
```

## Metrics

The following metrics are collected:

| Metric | Type | Description |
|--------|------|-------------|
| `kaos.agent.requests` | Counter | Total requests processed |
| `kaos.agent.request.duration` | Histogram | Request duration in seconds |
| `kaos.model.calls` | Counter | Total model API calls |
| `kaos.model.duration` | Histogram | Model call duration in seconds |
| `kaos.tool.calls` | Counter | Total tool executions |
| `kaos.tool.duration` | Histogram | Tool execution duration in seconds |
| `kaos.delegations` | Counter | Total agent delegations |
| `kaos.delegation.duration` | Histogram | Delegation duration in seconds |

All metrics include labels:
- `agent_name`: Name of the agent
- `status`: "success" or "error"

Tool metrics also include:
- `tool_name`: Name of the tool
- `mcp_server`: Name of the MCP server

Delegation metrics also include:
- `target_agent`: Name of the target agent

## Log Correlation

When OpenTelemetry is enabled, log entries automatically include trace context:

```
2024-01-15 10:30:45 INFO [trace_id=abc123 span_id=def456] Processing message...
```

This allows correlating logs with traces in your observability backend.

## Example: Agent with Full Telemetry

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: traced-agent
spec:
  modelAPI: my-modelapi
  model: "openai/gpt-4o"
  mcpServers:
  - calculator
  config:
    description: "Agent with full OpenTelemetry observability"
    instructions: "You are a helpful assistant with calculator access."
    telemetry:
      enabled: true
      endpoint: "http://otel-collector.monitoring.svc.cluster.local:4317"
  agentNetwork:
    access:
    - researcher
```

## Setting Up an OTel Collector

To collect telemetry, deploy an OpenTelemetry Collector in your cluster:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: monitoring
data:
  config.yaml: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318

    processors:
      batch:
        timeout: 10s

    exporters:
      otlp:
        endpoint: "your-backend:4317"
        tls:
          insecure: true

    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [batch]
          exporters: [otlp]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: otel-collector
  template:
    metadata:
      labels:
        app: otel-collector
    spec:
      containers:
      - name: collector
        image: otel/opentelemetry-collector:latest
        args: ["--config=/etc/otel/config.yaml"]
        ports:
        - containerPort: 4317
          name: otlp-grpc
        - containerPort: 4318
          name: otlp-http
        volumeMounts:
        - name: config
          mountPath: /etc/otel
      volumes:
      - name: config
        configMap:
          name: otel-collector-config
---
apiVersion: v1
kind: Service
metadata:
  name: otel-collector
  namespace: monitoring
spec:
  selector:
    app: otel-collector
  ports:
  - port: 4317
    name: otlp-grpc
  - port: 4318
    name: otlp-http
```

## Using with SigNoz

[SigNoz](https://signoz.io/) is an open-source APM that works well with KAOS:

1. Deploy SigNoz in your cluster:
```bash
helm repo add signoz https://charts.signoz.io
helm install signoz signoz/signoz -n monitoring --create-namespace
```

2. Configure agents to send telemetry to SigNoz:
```yaml
config:
  telemetry:
    enabled: true
    endpoint: "http://signoz-otel-collector.monitoring.svc.cluster.local:4317"
```

3. Access the SigNoz UI to view traces, metrics, and logs.

## Using with Uptrace

[Uptrace](https://uptrace.dev/) is another excellent option:

1. Deploy Uptrace:
```bash
helm repo add uptrace https://charts.uptrace.dev
helm install uptrace uptrace/uptrace -n monitoring --create-namespace
```

2. Configure agents:
```yaml
config:
  telemetry:
    enabled: true
    endpoint: "http://uptrace.monitoring.svc.cluster.local:14317"
```

## Environment Variables

The operator automatically sets these environment variables when telemetry is enabled:

| Variable | Description |
|----------|-------------|
| `OTEL_SDK_DISABLED` | "false" when telemetry is enabled (standard OTel env var) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint URL from `telemetry.endpoint` |
| `OTEL_SERVICE_NAME` | Defaults to CR name (agent or MCP server name) |
| `OTEL_RESOURCE_ATTRIBUTES` | Appends `service.namespace` and `kaos.resource.name` to user values |

For additional configuration, use standard [OpenTelemetry environment variables](https://opentelemetry-python.readthedocs.io/en/latest/sdk/environment_variables.html) via `spec.config.env`.

## Troubleshooting

### No traces appearing

1. Verify telemetry is enabled:
```bash
kubectl get agent my-agent -o jsonpath='{.spec.config.telemetry}'
```

2. Check agent logs for OTel initialization:
```bash
kubectl logs -l agent=my-agent | grep -i otel
```

3. Verify collector is reachable:
```bash
kubectl exec -it deploy/agent-my-agent -- curl -v http://otel-collector.monitoring:4317
```

### High latency

If telemetry adds noticeable latency:
- Use batching in the OTel collector
- Configure sampling via `OTEL_TRACES_SAMPLER` and `OTEL_TRACES_SAMPLER_ARG` env vars

### Missing spans

Ensure all sub-agents and MCP servers are instrumented:
- Each agent should have its own telemetry config
- MCP servers should also have telemetry enabled
- Trace context propagates automatically via W3C Trace Context headers
