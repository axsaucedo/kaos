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
cd python && source .venv/bin/activate
python -m pytest tests/ -v      # Tests
make lint                       # Linting (required for CI)

# Go (operator)
cd operator
make generate manifests         # After changing CRD types
make test-unit                  # Unit tests

# E2E (KIND cluster)
cd operator
make kind-create                # Create cluster with Gateway API
make kind-e2e-run-tests         # Full E2E suite
make kind-delete                # Cleanup
```

## Project Structure
```
python/                    # Agent runtime (pytest, black, ty)
├── agent/                 # Agent, RemoteAgent, AgentServer
├── mcptools/              # MCP tool client/server
└── modelapi/              # Model API client

operator/                  # K8s operator (Go, kubebuilder)
├── api/v1alpha1/          # CRD definitions
├── controllers/           # Reconcilers
├── config/                # CRD YAML, samples
└── tests/e2e/             # E2E tests (pytest)

.github/workflows/         # CI pipelines
.github/instructions/      # Path-specific instructions
```

## CRDs Overview
- **Agent**: AI agent with model API, MCP tools, and sub-agent delegation
- **MCPServer**: MCP tool server with Python runtime support
- **ModelAPI**: LLM proxy (LiteLLM) or hosted (Ollama) mode

## Key Files
- `operator/api/v1alpha1/*_types.go`: CRD schemas
- `operator/controllers/*_controller.go`: Reconciliation logic
- `operator/chart/`: Helm chart (generated from kustomize)
- `python/agent/client.py`: Agent runtime core

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
