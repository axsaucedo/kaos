# KAOS Memory Service

The `kaos_memory` package is the storage layer for KAOS production-grade agent memory. It provides two atomic, independently-testable stores that later phases compose into a deployable service:

- **`LongTermStore`** — wraps [Mem0](https://github.com/mem0ai/mem0) as a library and exposes scope-mapped `write` / `recall` / `delete` / `delete_scope`. It is the only importer of `mem0`. Owner scoping is applied inside the vector query so recall never crosses tenants.
- **`ShortTermStore`** — a scope-keyed relational short-term buffer with a token budget and a rolling summary. Overflow is folded into a summary rather than truncated, so nothing is silently lost and the summary is re-derivable from retained raw rows.

Both bind their models to a resolved OpenAI-compatible endpoint (a KAOS `ModelAPI`) via a single `ModelConfig`, and run in one of two storage modes:

| Mode | Vector store | Short-term table | Topology |
| --- | --- | --- | --- |
| `local` | embedded Chroma | SQLite | single container on one PVC |
| `external` | pgvector | Postgres | stateless, shared Postgres |

## Scope model

A `Scope` names whose memory an operation touches and maps onto a Mem0 owner identifier:

| Scope level | Mem0 owner key |
| --- | --- |
| `private` | `agent_id` (this agent) |
| `user` | `user_id` (a principal) |
| `session` | `run_id` (one run) |
| `shared` | a reserved shared owner id on `agent_id` |

`shared` resolves to a reserved owner id rather than an empty filter because Mem0 rejects an owner-less search. This module ships only the correct translation; fail-closed enforcement is a later phase.

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
| `scope.py` | the `Scope` value object and its Mem0 owner mapping |
| `longterm.py` | the Mem0-backed long-term adapter |
| `shortterm.py` | the relational short-term store |
| `tokens.py` | token counting for the short-term budget |
| `models.py` | the OpenAI-compatible model client (summarization) |

The HTTP service, the agent-runtime client, and the operator wiring that resolves this configuration from a `MemoryStore` resource are built in subsequent phases.
