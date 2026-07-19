# KAOS Memory

`kaos-memory` is the production-grade agent memory library for KAOS: one package that owns the wire contract, the tiered storage engine and HTTP service, the service client, and an optional Pydantic AI integration. It is packaged so consumers only pull what they use.

| Install | Modules | Dependencies |
| --- | --- | --- |
| `kaos-memory` (core) | `kaos_memory.contract`, `kaos_memory.client` | Pydantic + httpx only |
| `kaos-memory[service]` | `kaos_memory.app`, `kaos_memory.stores`, `kaos_memory.config` | + Mem0, Chroma/pgvector, tiktoken, FastAPI |
| `kaos-memory[pydantic-ai]` | `kaos_memory.pydantic_ai` | + Pydantic AI |

- **`kaos_memory.contract`** — the HTTP contract: `Scope` selects reads/erasure, while level-less `Attribution` carries write identities.
- **`kaos_memory.client`** — `MemoryServiceClient`, the framework-agnostic best-effort HTTP client for the service (recall degrades to empty; write/forget are fail-soft unless `failure_mode="strict"`).
- **`kaos_memory.pydantic_ai`** — direct Pydantic AI integration: message/turn adapters (`pydantic_message_to_turns`, `reconstruct_message_history`), server-side scope derivation (`scope_from_deps`), and the opt-in memory toolset (`MemoryTools`, `build_memory_toolset`).

The service (`[service]` extra) composes two atomic, independently-testable stores:

- **`LongTermStore`** — wraps [Mem0](https://github.com/mem0ai/mem0) as a library and exposes scope-mapped `write` / `recall` / `delete` / `delete_scope`. It is the only importer of `mem0`. Writes preserve compound user/agent attribution plus session/group metadata, and scope filters are applied inside vector queries so recall never crosses the selected boundary.
- **`ShortTermStore`** — a per-session relational short-term buffer bounding a verbatim recency window by a token budget, with an opt-in fold that compacts evicted turns into a versioned per-session medium-term digest rather than truncating them. Every key combines the store group and session id, never the writing agent or principal, so the same run is addressable through any entitled recall scope while concurrent sessions never interleave raw turns. Folding is amortised by high/low water marks (evict down to the low mark on crossing the high mark), the digest is kept as append-only versions under a retention cap, and each fold's evicted batch is returned so callers can cascade it to long-term extraction. On Postgres the window is an UNLOGGED table and folds are serialised per session by an advisory lock so replicas cannot double-fold.

Both bind their models to a resolved OpenAI-compatible endpoint (a KAOS `ModelAPI`) via a single `ModelConfig`, and run in one of two storage modes:

| Mode | Vector store | Short-term table | Topology |
| --- | --- | --- | --- |
| `local` | embedded Chroma | SQLite | single container on one PVC |
| `external` | pgvector | Postgres | stateless, shared Postgres |

## Scope model

A `Scope` selects long-term read visibility and erasure. An `Attribution` write carries every verified contributor (`user_id` and real `agent_id`) plus session/group metadata, with no scope level. The service authoritatively enforces `KAOS_MEMORY_REQUIRE_PRINCIPAL` and `KAOS_MEMORY_REQUIRE_AGENT_IDENTITY`; runtime checks are defence in depth.

| Scope level | Long-term read filter |
| --- | --- |
| `agent` | `agent_id = <real agent identity>` |
| `user` | `user_id = <principal>`; includes everything that user contributed through any agent/session |
| `session` | `user_id = "*"`, `kaos_run = <session id>` |
| `group` | `user_id = "*"`, `kaos_group = <active collection name>` |

The wildcard is the pinned Mem0 2.0.10 convention required for custom-metadata filters. The group value is the configured local/external collection name because one `MemoryStore` is the physical group boundary; there is no synthetic agent sentinel. User/agent erasure uses native entity deletion, while session/group erasure filters custom attribution and deletes matching ids when Mem0 lacks a filtered-delete surface.

Short- and medium-term keys have the form `kaos_group:<store group>|run:<session id>` (or just `run:<session id>` without a configured group) for every scope. A missing session id fails loudly. The store group is the tenant boundary and the unguessable run id is the capability used through the scoped service and its network/RBAC boundary. A separate attribution index preserves user-, agent-, and group-level erasure without putting those identities into the session key. Group scope therefore shares extracted long-term facts across agents, not raw turns across sessions.

## Development

```bash
make build            # install with dev extras into the active venv
make test             # run the unit tests
make lint             # black --check + ty type check
make format           # black
```

### Running the pgvector / Postgres tests

The `external`-mode tests are gated behind the `pgvector` marker and a DSN env var. Start a local container and point the tests at it:

```bash
docker run -d --name kaos-pgv \
  -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=memdb \
  -p 55432:5432 pgvector/pgvector:pg16

export KAOS_TEST_PGVECTOR_DSN=postgresql://postgres:pw@localhost:55432/memdb
pytest tests/ -v
```

Without the DSN set, the `pgvector`-marked tests are skipped and the local Chroma/SQLite tests run on their own.

## Layout

| Module | Purpose |
| --- | --- |
| `config.py` | typed storage, model and short-term tier configuration |
| `stores.py` | the whole storage layer: the `Scope` value object and Mem0 owner mapping, token counting, the OpenAI-compatible model client, the relational short-term store, and the Mem0-backed long-term adapter |

The HTTP service, the agent-runtime client, and the operator wiring that resolves this configuration from a `MemoryStore` resource are built in subsequent phases.
