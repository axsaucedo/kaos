# KAOS sync service

A lightweight external service that synchronizes KAOS custom resources into the Agentic Identity Broker (AIB), giving each agent an AIB-issued identity and the permission grants implied by its declared MCP server usage.

## What it does

The service watches KAOS `Agent` and `MCPServer` resources and projects them into AIB using a stable bootstrap encoding:

- Each `MCPServer` `<ns>/<name>` becomes a synthetic AIB service with `client_id` `kaos-mcpserver-<ns>-<name>` exposing a single `call` scope.
- Each requested `Agent -> MCPServer` edge becomes an AIB permission set `kaos:mcpserver:<ns>:<mcp>:call`.
- Each `Agent` becomes an AIB *local* agent (no `client_id`, so AIB mints the actor token locally) bound to the permission sets for its edges.

For every projected agent, the service obtains AIB client credentials and writes them into a Kubernetes Secret named `kaos-aib-<agent-id>` for the operator to mount into the agent pod.

## Layout

- `kaos_sync/projection.py` — pure projection of KAOS resources into desired AIB records (no I/O).
- `kaos_sync/aib_client.py` — AIB admin API client.
- `kaos_sync/reconcile.py` — reconcile loop and credential Secret writing.
- `kaos_sync/config.py` — settings.
- `kaos_sync/main.py` — entrypoint.

## Development

```bash
make install
make lint
make test
```
