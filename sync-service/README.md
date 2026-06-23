# kaos-sync

The KAOS↔AIB sync service. It is a standalone `controller-runtime` manager that
projects KAOS `Agent` / `MCPServer` / `ModelAPI` resources into the Agentic
Identity Broker (AIB) admin model and provisions the per-agent credential
`Secret`s that the operator mounts into agent pods.

The framework supplies the watch, informer cache, leader election, periodic
resync and requeue/backoff; the service code is just the projection, the AIB
admin calls and the Secret provisioning.

## What it does

1. **Project** KAOS resources into the AIB admin model — each external dependency
   an agent declares (`spec.mcpServers`, `spec.modelAPI`) becomes a synthetic AIB
   service exposing a single `call` scope, each requested edge becomes a
   permission set, and each Agent becomes a local AIB agent bound to those
   permission sets. Logical identity is always `kaos://<kind>/<namespace>/<name>`,
   unique by construction.
2. **Provision** a per-agent credential `Secret` (`client_id` / `client_secret`)
   by minting against the broker. The Secret name is `<prefix>-<agent>` (default
   prefix `kaos-aib`), matching the operator's
   `security.agentAuth.credentialSecretPrefix`.
3. **Fail closed** — an agent whose permission sets could not all be created is
   skipped (no credentials minted), and the reconcile requeues with backoff.
4. **Prune** orphaned broker records and credential Secrets that are no longer in
   the desired state, in dependency-safe order.

The projection is a pure, whole-world function (identity-collision resolution
needs every resource of a kind), so every watched change funnels to a single
sentinel reconcile request that the workqueue coalesces into one full pass.

## Layout

```
cmd/main.go            Entrypoint: env-only config + controller-runtime manager
internal/projection    Pure KAOS -> AIB projection (no I/O, unit tested)
internal/aib           Thin idempotent AIB admin REST client (retryablehttp)
internal/sync          The sentinel-request reconciler (SSA Secret upsert, prune)
chart/                 Helm chart (Deployment, RBAC, ServiceAccount)
Dockerfile             Multi-stage distroless build -> axsauze/kaos-sync
```

## Configuration

Environment-only (see `Settings` in `cmd/main.go`):

| Env var | Default | Purpose |
|---------|---------|---------|
| `AIB_ADMIN_URL` | `http://localhost:14000/api` | Broker admin API base URL |
| `AIB_PRINCIPAL` | `kaos-sync` | Pre-authenticated principal |
| `AIB_PRINCIPAL_HEADER` | `X-Remote-User` | Header carrying the principal |
| `KAOS_SYNC_NAMESPACES` | _(empty = cluster-wide)_ | CSV of namespaces to reconcile |
| `KAOS_SYNC_CREDENTIAL_SECRET_PREFIX` | `kaos-aib` | Per-agent Secret name prefix |
| `KAOS_SYNC_RECONCILE_INTERVAL` | `30s` | Safety-net resync period |
| `KAOS_SYNC_REQUEST_TIMEOUT` | `10s` | Per-request timeout to the broker |
| `KAOS_SYNC_PRUNE_ENABLED` | `true` | Delete orphaned broker records/Secrets |
| `KAOS_SYNC_LEADER_ELECTION_ENABLED` | `true` | Lease-based HA leader election |
| `POD_NAMESPACE` | `kaos-system` | Leader-election lease namespace |
| `KAOS_SYNC_HEALTH_PROBE_ADDRESS` | `:8081` | `/healthz` and `/readyz` |
| `KAOS_SYNC_METRICS_ADDRESS` | `:8080` | Prometheus metrics endpoint |

## Development

```bash
make build          # compile bin/kaos-sync
make test           # go test ./...
make lint           # gofmt check + go vet
make docker-build   # build axsauze/kaos-sync:dev
```
