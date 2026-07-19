# MemoryStore CRD

The MemoryStore custom resource provisions a central, long-term memory service that agents share. It runs the KAOS memory engine (Mem0) behind a stable in-cluster endpoint, backing it with either pod-local storage for development or an external pgvector database for production. Agents bind to a MemoryStore through their `config.memory` block to gain semantic, cross-session memory on top of the runtime's local short-term window.

## Full Specification

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MemoryStore
metadata:
  name: shared-memory
  namespace: my-namespace
spec:
  # Memory engine (default: mem0)
  engine: mem0

  # Required: storage backend
  storage:
    # "local" for a single-replica PVC-backed store, "external" for pgvector
    type: local

    # For local storage: chroma vector store on a persistent volume
    local:
      provider: chroma          # only chroma is supported
      persistentVolume:
        size: "5Gi"             # default 5Gi
      collection: kaos_memory   # vector collection name (default kaos_memory)

    # For external storage: managed pgvector database
    # external:
    #   provider: pgvector       # only pgvector is supported
    #   connectionSecretRef:     # secret holding the DSN
    #     name: pgvector-dsn
    #     key: dsn
    #   embeddingDims: 1536      # vector dimensions (default 1536)
    #   collection: kaos_memory  # vector collection name (default kaos_memory)

  # Replicas override. When unset, defaults by storage mode: external stores
  # run 2 replicas for availability, local stores run 1. Must be 1 in local mode.
  # replicas: 2

  # Required: models used for extraction and embedding
  models:
    summarization:
      modelAPI: my-modelapi     # ModelAPI in the same namespace
      model: gpt-4o-mini
    embedding:
      modelAPI: my-modelapi
      model: text-embedding-3-small

  # Optional: verbatim short-term window tuning
  shortTerm:
    tokenBudget: 4096           # token bound on the verbatim window (default 4096)
    hardEventCap: 2000          # event-count ceiling on the window (default 2000)

  # Optional: medium-term rolling digest tuning (folds short-term overflow)
  mediumTerm:
    enabled: false              # rolling digest off by default (overflow is dropped)
    compactionTrigger: 0        # fold trigger in tokens; 0 = tokenBudget
    compactionTarget: 0         # fold target in tokens; 0 = tokenBudget / 2
    digestRetention: 20         # digest versions retained (default 20)
    systemPrompt: ""            # summariser prompt override (default: built-in)

  # Optional: long-term semantic tier tuning (recall shape + fact extraction)
  longTerm:
    enabled: true               # false skips extraction and recalls no facts
    defaultTopK: 10             # recall result count when a request omits top_k
    # scoreThreshold: 0.4       # minimum similarity in [0,1]; unset = no threshold
    rerank: false               # engine reranking of recalled facts
    extraction:
      concurrency: 4            # concurrent extraction workers (default 4)
      maxRetries: 2             # retries per failed extraction task (default 2)
      systemPrompt: ""          # fact-extraction prompt override (default: built-in)

  # Optional: bounded request executor size (default 8)
  requestConcurrency: 8

  # Default write/forget failure mode for bound agents (default: soft)
  # "soft" tolerates memory-write failures; "strict" surfaces them as errors.
  defaultFailureMode: soft

  # Default read scope for agents that omit config.memory.defaultReadScope.
  # When omitted, agents fall back to "agent".
  defaultReadScope: agent
```

## Storage Modes

### Local

Local mode runs a single memory-service replica backed by a `chroma` vector store on a PersistentVolumeClaim. It is intended for development and single-node clusters. `replicas` must be `1` — the CRD rejects higher values in local mode because the PVC is not shared across pods.

```yaml
spec:
  storage:
    type: local
    local:
      provider: chroma
      persistentVolume:
        size: "5Gi"
```

### External

External mode connects the memory service to a managed pgvector database via a DSN stored in a Kubernetes Secret. Because the service is stateless over the shared database, this mode runs multiple replicas and is the production path.

```yaml
spec:
  storage:
    type: external
    external:
      provider: pgvector
      connectionSecretRef:
        name: pgvector-dsn
        key: dsn
      embeddingDims: 1536
  # replicas defaults to 2 in external mode; set explicitly to override
```

The DSN is injected into the service as `KAOS_MEMORY_EXTERNAL_DSN` via a `secretKeyRef`, and `embeddingDims` is passed as `KAOS_MEMORY_EXTERNAL_DIMS`. The referenced Secret must exist in the same namespace. External stores default to two replicas guarded by a `PodDisruptionBudget` (see [High availability and operations](#high-availability-and-operations)).

## Models

Both `summarization` and `embedding` model references are required. Each points at a `ModelAPI` in the same namespace plus a concrete model name. The controller resolves the referenced ModelAPIs and holds the MemoryStore in `Pending` until they are `Ready`; the summarization ModelAPI's cluster-local Service endpoint (suffixed with `/v1`) becomes the service's model base URL. Generated ModelAPI NetworkPolicies admit same-namespace MemoryStore pods for this direct model traffic while other workload pods remain gateway-only. Models bind lazily at first use, so the store can reach `Ready` from storage reachability before any embedding or summarization call is made.

| Field | Type | Description |
|-------|------|-------------|
| `models.summarization.modelAPI` | string | ModelAPI providing the summarization/extraction model |
| `models.summarization.model` | string | Summarization model name |
| `models.embedding.modelAPI` | string | ModelAPI providing the embedding model |
| `models.embedding.model` | string | Embedding model name |

## Memory Tiers

The `shortTerm`, `mediumTerm`, and `longTerm` blocks tune the three memory tiers as typed fields. Every field is optional: an absent field projects nothing onto the service, leaving the memory-service default in place, and an explicit `container.env` entry still overrides the projected value.

- **shortTerm** bounds the verbatim conversation window by `tokenBudget` and `hardEventCap`.
- **mediumTerm** opts into the rolling digest that folds short-term overflow instead of dropping it. Folding is amortised by two compaction marks: `compactionTrigger` (fold starts) and `compactionTarget` (fold evicts down to). `0` means derived — the token budget and half the token budget respectively. The CRD enforces the service invariant at apply time: `0 < compactionTarget < compactionTrigger <= tokenBudget` (after derivation), so a misconfigured store is rejected by `kubectl apply` instead of crash-looping at pod startup.
- **longTerm** shapes semantic recall (`defaultTopK`, `scoreThreshold`, `rerank`) and the fact-extraction executor (`extraction`). Setting `enabled: false` turns the semantic tier off by configuration: writes skip fact extraction entirely and recall returns no facts (not degraded); the conversational tiers keep working.

## Spec Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `engine` | string | `mem0` | Memory engine. Only `mem0` is supported |
| `storage.type` | string | — | `local` or `external` (required) |
| `storage.local.provider` | string | `chroma` | Local vector store provider |
| `storage.local.persistentVolume.size` | string | `5Gi` | PVC size for local storage |
| `storage.external.provider` | string | `pgvector` | External vector store provider |
| `storage.external.connectionSecretRef` | SecretKeySelector | — | Secret + key holding the pgvector DSN (required for external) |
| `storage.external.embeddingDims` | int | `1536` | Embedding vector dimensions |
| `storage.local.collection` / `storage.external.collection` | string | `kaos_memory` | Vector collection name |
| `replicas` | int | mode-aware | Service replicas. Defaults to 2 for external, 1 for local. Must be 1 in local mode |
| `models.summarization` | object | — | Summarization/extraction model reference (required) |
| `models.embedding` | object | — | Embedding model reference (required) |
| `shortTerm.tokenBudget` | int | `4096` | Token bound on the verbatim short-term window |
| `shortTerm.hardEventCap` | int | `2000` | Event-count ceiling on the short-term window |
| `mediumTerm.enabled` | bool | `false` | Fold short-term overflow into the rolling digest instead of dropping it |
| `mediumTerm.compactionTrigger` | int | `0` | Token level that triggers a fold; `0` derives it from `tokenBudget` |
| `mediumTerm.compactionTarget` | int | `0` | Token level a fold evicts down to; `0` derives `tokenBudget / 2` |
| `mediumTerm.digestRetention` | int | `20` | Digest versions retained |
| `mediumTerm.systemPrompt` | string | built-in | Summariser prompt override for digest folds |
| `longTerm.enabled` | bool | `true` | Long-term tier switch; `false` skips extraction and recalls no facts |
| `longTerm.defaultTopK` | int | `10` | Recall result count when a request omits `top_k` |
| `longTerm.scoreThreshold` | float | unset | Minimum similarity score for recalled facts, in `[0,1]` |
| `longTerm.rerank` | bool | `false` | Engine reranking of recalled facts |
| `longTerm.extraction.concurrency` | int | `4` | Concurrent extraction workers |
| `longTerm.extraction.maxRetries` | int | `2` | Retries per failed extraction task |
| `longTerm.extraction.systemPrompt` | string | built-in | Fact-extraction prompt override |
| `requestConcurrency` | int | `8` | Bounded request executor size |
| `defaultFailureMode` | string | `soft` | Default write/forget failure mode for bound agents (`soft` or `strict`) |
| `defaultReadScope` | string | `session` | Default automatic read scope for bound agents: `agent`, `user`, `group`, or `session`; an Agent `config.memory.defaultReadScope` overrides it |

## Status

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | `Pending`, `Ready`, or `Failed` |
| `ready` | bool | Whether the store is serving |
| `endpoint` | string | In-cluster service URL agents connect to |
| `message` | string | Human-readable status detail |
| `deployment` | object | Underlying Deployment status |

When ready, the store exposes an endpoint of the form `http://memorystore-<name>.<namespace>.svc.cluster.local:8080`, which the operator injects into bound agents as `MEMORY_STORE_ENDPOINT`.

## High availability and operations

**Replicas and disruption budget.** External stores are stateless over the shared pgvector database, so they default to two replicas and are guarded by a `PodDisruptionBudget` pinning `minAvailable: 1` — voluntary disruptions (node drains, rollouts) cannot drain the fleet to zero. Local stores are single-writer over a PersistentVolume and stay at one replica with no budget. Set `replicas` explicitly to override the external default; local mode rejects any value other than 1.

**Health and readiness.** The service exposes `/healthz` (liveness: the process is up) and `/readyz` (readiness: both memory tiers are reachable, returning 503 otherwise). The operator wires these as the Deployment's liveness and readiness probes, so a store only reports `Ready` once it can serve.

**Failure mode and degradation.** The store's `defaultFailureMode` (`soft` by default) governs how write and forget failures surface to bound agents. Under `soft`, a memory-write failure is tolerated: the agent's turn proceeds and the write is retried in the background. Under `strict`, the failure is surfaced as an error. Recall is always best-effort regardless of mode — if the long-term tier is unavailable, recall degrades to the short-term window rather than failing the turn. An individual Agent can override the store default in its `config.memory.failureMode`.

**Default read scope.** `defaultReadScope` supplies the automatic recall level for bound agents that omit their own value. Resolution is Agent `defaultReadScope`, then store `defaultReadScope`, then `session`.

**Provisioning a development database.** For local development, `kaos system install --pgvector-memory-enabled` provisions a pgvector Postgres in the install namespace and writes a `kaos-memory-pgvector` connection Secret, ready to reference from an `external`-mode store's `connectionSecretRef`. This is a development convenience — production deployments point `connectionSecretRef` at a managed pgvector database.

## Binding an Agent

Agents attach to a MemoryStore through their `config.memory` block. See the [Agent CRD](./agent-crd.md) memory section for the full binding surface (type, read scopes, tools, and failure mode).

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: assistant
  namespace: my-namespace
spec:
  modelAPI: my-modelapi
  model: gpt-4o-mini
  config:
    memory:
      type: remote
      memoryStore: shared-memory
      defaultReadScope: user
      tools: all
```

Memory binding is degraded-aware once an agent is running: if the referenced MemoryStore later becomes missing or not ready, the agent keeps serving and reports a `MemoryDegraded` status condition, falling back to its pod-local short-term window until the store becomes available. The agent's initial creation, however, waits for the bound store: with `waitForDependencies` enabled (the default), an agent whose MemoryStore is missing or not yet ready stays `Waiting` until the store is Ready, so it never starts up degraded.
