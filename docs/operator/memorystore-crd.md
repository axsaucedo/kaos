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

    # For external storage: managed pgvector database
    # external:
    #   provider: pgvector       # only pgvector is supported
    #   connectionSecretRef:     # secret holding the DSN
    #     name: pgvector-dsn
    #     key: dsn
    #   embeddingDims: 1536      # vector dimensions (default 1536)

  # Replicas (default 1). Must be 1 in local storage mode.
  replicas: 1

  # Required: models used for extraction and embedding
  models:
    summarization:
      modelAPI: my-modelapi     # ModelAPI in the same namespace
      model: gpt-4o-mini
    embedding:
      modelAPI: my-modelapi
      model: text-embedding-3-small

  # Optional: knowledge extraction tuning
  extraction:
    concurrency: 4              # concurrent extraction workers (default 4)

  # Default write/forget failure mode for bound agents (default: soft)
  # "soft" tolerates memory-write failures; "strict" surfaces them as errors.
  defaultFailureMode: soft
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

External mode connects the memory service to a managed pgvector database via a DSN stored in a Kubernetes Secret. This mode supports multiple replicas and is the production path.

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
  replicas: 2
```

The DSN is injected into the service as `KAOS_MEMORY_EXTERNAL_DSN` via a `secretKeyRef`, and `embeddingDims` is passed as `KAOS_MEMORY_EXTERNAL_DIMS`. The referenced Secret must exist in the same namespace.

## Models

Both `summarization` and `embedding` model references are required. Each points at a `ModelAPI` in the same namespace plus a concrete model name. The controller resolves the referenced ModelAPIs and holds the MemoryStore in `Pending` until they are `Ready`; the summarization endpoint (suffixed with `/v1`) becomes the service's model base URL. Models bind lazily at first use, so the store can reach `Ready` from storage reachability before any embedding or summarization call is made.

| Field | Type | Description |
|-------|------|-------------|
| `models.summarization.modelAPI` | string | ModelAPI providing the summarization/extraction model |
| `models.summarization.model` | string | Summarization model name |
| `models.embedding.modelAPI` | string | ModelAPI providing the embedding model |
| `models.embedding.model` | string | Embedding model name |

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
| `replicas` | int | `1` | Service replicas; must be `1` in local mode |
| `models.summarization` | object | — | Summarization/extraction model reference (required) |
| `models.embedding` | object | — | Embedding model reference (required) |
| `extraction.concurrency` | int | `4` | Concurrent extraction workers |
| `defaultFailureMode` | string | `soft` | Default write/forget failure mode for bound agents (`soft` or `strict`) |

## Status

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | `Pending`, `Ready`, or `Failed` |
| `ready` | bool | Whether the store is serving |
| `endpoint` | string | In-cluster service URL agents connect to |
| `message` | string | Human-readable status detail |
| `deployment` | object | Underlying Deployment status |

When ready, the store exposes an endpoint of the form `http://memorystore-<name>.<namespace>.svc.cluster.local:8080`, which the operator injects into bound agents as `MEMORY_STORE_ENDPOINT`.

## Binding an Agent

Agents attach to a MemoryStore through their `config.memory` block. See the [Agent CRD](./agent-crd.md) memory section for the full binding surface (type, scope, tools, and failure mode).

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
      scope: user
      tools: all
```

Memory binding is degraded-aware: if the referenced MemoryStore is missing or not yet ready, the agent still serves and reports a `MemoryDegraded` status condition, falling back to its pod-local short-term window until the store becomes available.
