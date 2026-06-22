# KAOS sync service

A lightweight external service that synchronizes KAOS custom resources into the Agentic Identity Broker (AIB), giving each agent an AIB-issued identity and the permission grants implied by its declared MCP server usage.

## What it does

The service watches KAOS `Agent`, `MCPServer` and `ModelAPI` resources and projects them into AIB using a stable bootstrap encoding:

- Each `MCPServer` `<ns>/<name>` becomes a synthetic AIB service with `client_id` `kaos-mcpserver-<ns>-<name>` exposing a single `call` scope.
- Each `ModelAPI` `<ns>/<name>` becomes a synthetic AIB service with `client_id` `kaos-modelapi-<ns>-<name>` exposing a single `call` scope.
- Each requested `Agent -> MCPServer` or `Agent -> ModelAPI` edge becomes an AIB permission set `kaos:<kind>:<ns>:<target>:call`.
- Each `Agent` becomes an AIB *local* agent (no `client_id`, so AIB mints the actor token locally) bound to the permission sets for its edges.

For every projected agent, the service obtains AIB client credentials and writes them into a Kubernetes Secret named `kaos-aib-<agent-id>` for the operator to mount into the agent pod.

The reconcile loop is resilient: every service, permission set and agent is reconciled in isolation, so a single broker or resource failure is recorded as a categorized problem without aborting the pass. KAOS-owned broker records and credential Secrets that no longer correspond to a live KAOS resource are pruned (controllable via `KAOS_SYNC_PRUNE_ENABLED`). Broker admin requests use bounded exponential-backoff retries.

## Observability

- Metrics are pushed via OTLP to the endpoint in `OTEL_EXPORTER_OTLP_ENDPOINT` (using `OTEL_SERVICE_NAME`, default `kaos-sync`), including reconcile pass counts, minted credentials, projected resource counts and problems by category. Export is enabled only when both env vars are set.
- Liveness probe at `/healthz` and readiness probe at `/readyz` on `KAOS_SYNC_HEALTH_PORT` (default `8080`); readiness flips to ready after the first reconcile pass completes.

## Layout

- `kaos_sync/projection.py` — pure projection of KAOS resources into desired AIB records (no I/O).
- `kaos_sync/aib_client.py` — AIB admin API client with bounded retries.
- `kaos_sync/reconcile.py` — reconcile loop, pruning and credential Secret writing.
- `kaos_sync/observability.py` — OTLP metric export and health/readiness endpoints.
- `kaos_sync/config.py` — settings.
- `kaos_sync/main.py` — entrypoint.

## Development

```bash
make install
make lint
make test
```
