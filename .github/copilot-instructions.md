# KAOS (K8s Agent Orchestration System)

Kubernetes-native AI agent orchestration framework.

## Quick Reference

## Key Principles
- **KEEP IT SIMPLE** - Avoid over-engineering
- Tests AND linting are the success criteria for development
- Conventional commits after every task (not at the end)
- End-to-end tests can be run in github actions CI; push a PR and track progress
- Review the module specific instructions under .github/instructions for context
- Update documentation, .github/copilot-instructions.md and .github/instructions/* after changes; keep it succinct and functional

### Commit Guidelines
Use conventional commits: `feat(scope):`, `fix(scope):`, `refactor(scope):`, `test(scope):`, `docs:` - keep it functional and succinct. 

### Build & Test Commands

You perform all changes in Pull Requests. All tests run inside the pull requests, so you can push. End to end runs are fastest in PR github actions, so you can create a PR and push to review. 

Running local tests for python and golang operator is possible, and running individual or handful of e2e tests is also encouraged, but for end-to-end create and push a PR.

```bash
# Python (agent framework)
cd pydantic-ai-server && source .venv/bin/activate
python -m pytest tests/ -v      # Tests
make lint                       # Linting (required for CI)

# CLI (kaos-cli)
cd kaos-cli && source .venv/bin/activate
python -m pytest tests/ -v      # CLI integration tests

# Memory service + library (kaos-memory)
cd kaos-memory
uv run pytest tests/ -v         # Tests
make lint                       # Linting (black --check + ty)

# Go (operator)
cd operator
make generate manifests         # After changing CRD types
make test-unit                  # Unit tests

# E2E (KIND cluster)
cd operator
make kind-create                # Create cluster with Gateway API + MetalLB (uses kaos CLI)
make kind-e2e-run-tests         # Full E2E suite
make kind-delete                # Cleanup

# Or use kaos CLI directly
kaos system install --gateway-enabled --metallb-enabled --wait
```

## Project Structure
```
pydantic-ai-server/        # Agent runtime (Pydantic AI, pytest, black, ty) — git subtree
├── pais/             # AgentServer, tools, memory, A2A
│   ├── server.py      # AgentServer, create_agent_server, routes
│   ├── serverutils.py # AgentDeps, AgentCard (Pydantic), RemoteAgent (A2A + chat delegation), AgentServerSettings
│   ├── a2a.py         # TaskManager ABC, LocalTaskManager, NullTaskManager, Task data model, JSON-RPC, setup_a2a_routes
│   ├── tools.py       # DelegationToolset, string-mode handler
│   ├── memory.py      # Memory ABC, LocalMemory, RemoteMemory, NullMemory
│   └── telemetry.py   # OpenTelemetry instrumentation

mcp-servers/               # Standalone MCP server implementations
├── python-string/         # Python code execution runtime
└── fastmcp-codemode/      # MCP server aggregator with CodeMode transform

kaos-memory/               # Memory library + central service (kaos_memory, uv, pytest, black, ty)
├── kaos_memory/
│   ├── contract.py        # Scope/identity model, recall/write/forget request+response types
│   ├── client.py          # MemoryServiceClient (soft/strict failure mode; recall degrades)
│   ├── app.py             # MemoryService (Mem0 + FastAPI), BackgroundRunner extraction
│   └── ...                # pydantic-ai adapters + toolset (extras: [service], [pydantic-ai])
└── tests/                 # Unit + cross-component tests

kaos-cli/                  # CLI tool
├── kaos_cli/system/       # System commands (install, create-rbac)
├── kaos_cli/mcp/          # MCP commands (init, build, deploy)
├── kaos_cli/agent/        # Agent commands (deploy, invoke, a2a, status, memory)
├── kaos_cli/modelapi/     # ModelAPI commands
├── kaos_cli/samples/      # Samples commands (list, deploy, delete)
└── tests/                 # CLI integration tests (dry-run YAML validation)

operator/                  # K8s operator (Go, kubebuilder)
├── api/v1alpha1/          # CRD definitions
├── controllers/           # Reconcilers
├── config/                # CRD YAML, samples
└── tests/e2e/             # E2E tests (pytest)

tmp/                       # Local work files (gitignored)

.github/workflows/         # CI pipelines
.github/instructions/      # Path-specific instructions
```

## CRDs Overview
- **Agent**: AI agent with model API, MCP tools, sub-agent delegation, autonomous (self-looping) execution, and memory binding (`config.memory`: `agent`/`user`/`group`/`session` scope, tools, failureMode, clientParams)
- **MCPServer**: MCP tool server with runtime-based architecture (python-string, fastmcp-codemode, pctx-codemode, kubernetes, slack, custom)
- **ModelAPI**: LLM proxy (LiteLLM) or hosted (Ollama) mode
- **MemoryStore**: central memory service backing long-term semantic memory (local or external pgvector storage; external defaults to 2 replicas + PDB; summarization/embedding model refs; `--pgvector-memory-enabled` installs dev Postgres)

## Authorization (optional, enabled by security presets)
Envoy Gateway verifies agent JWTs and calls the fail-closed `kaos-pdp` OPA Service over gRPC external authorization. `AuthzProjectionReconciler` projects `policy.rego` plus `data.json` from CRDs; the published data contract is `data.kaos.grants`, issuer-keyed `data.kaos.jwks`, and `data.kaos.agents`. Identity provider selection is `serviceaccount`, `aib`, or `oidc`; AIB provisions identity credentials only. Policy data is `automated` or `manual`. Enable with `kaos system install --auth-enabled <preset>` (`kaos-internal`, `aib-only`, or `aib-keycloak`). See `docs/security/authorization.md`.

## Key Files
- `operator/api/v1alpha1/*_types.go`: CRD schemas
- `operator/controllers/*_controller.go`: Reconciliation logic
- `operator/controllers/authz_projection_controller.go`: Authorization policy ConfigMap + identity projection
- `operator/internal/authz/`: Static policy rego, data document builder, JWKS fetch, published `data-schema.md`
- `operator/chart/`: Helm chart (generated from kustomize)
- `pydantic-ai-server/pais/server.py`: AgentServer, create_agent_server, routes, _run_autonomous
- `pydantic-ai-server/pais/serverutils.py`: AgentDeps, AgentCard (Pydantic BaseModel, A2A-compliant), RemoteAgent (A2A + chat delegation), AgentServerSettings
- `pydantic-ai-server/pais/a2a.py`: TaskManager ABC, LocalTaskManager, NullTaskManager, Task data model, JSON-RPC, autonomous execution, setup_a2a_routes
- `pydantic-ai-server/pais/tools.py`: DelegationToolset (AbstractToolset), string-mode handler
- `pydantic-ai-server/pais/memory.py`: RemoteMemory adapter over kaos-memory MemoryServiceClient (+ re-exports)
- `kaos-memory/kaos_memory/contract.py`: scope/identity model + recall/write/forget types
- `kaos-memory/kaos_memory/client.py`: MemoryServiceClient (soft/strict failure mode)
- `kaos-memory/kaos_memory/app.py`: MemoryService (Mem0 + FastAPI), BackgroundRunner
- `operator/controllers/memorystore_controller.go`: MemoryStore reconciler (Deployment/Service/PDB, replica defaulting)

## Testing Notes

### E2E on macOS/KIND
MetalLB IPs (172.18.0.x) aren't accessible from host. Use:
```bash
kubectl port-forward -n envoy-gateway-system svc/envoy-gateway 8888:80 &
export GATEWAY_URL=http://localhost:8888
```

## Domain-Specific Instructions
Detailed instructions are in `.github/instructions/`:
- `e2e.instructions.md`: E2E test setup, structure, gotchas and fast testing
- `python.instructions.md`: Data Plane Python runtime framework details
- `operator.instructions.md`: Control Plane Golang operator development
- `docs.instructions.md`: VitePress docs, mermaid diagrams, multi-version builds
- `release.instructions.md`: Release process, versioning, CI pipeline, validation checklist

### Skills
- `/release-kaos`: Invoke with a version (e.g., "Use /release-kaos to release v0.5.0") — executes full release pipeline
- `/planned-implementation`: Use for complex staged KAOS work that needs backend/UI context gathering, a written plan, task-scoped commits, PR/CI validation, and an uncommitted REPORT.md PR comment
- `/dependabot-fix`: Invoke with a PR number (e.g., "Use /dependabot-fix 142") — diagnoses and fixes a single failing Dependabot PR autonomously, commits on the PR branch, posts a REPORT.md comment, and emits a machine-readable `RESULT:` line
- `/dependabot-fix-all`: Invoke with no arguments — orchestrator that fixes every open Dependabot PR end-to-end on autopilot, spawning one isolated non-interactive `copilot -p` child per PR (serial), verifying each via `gh`, and recording state in the SQLite ledger
