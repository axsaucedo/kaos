# KAOS (K8s Agent Orchestration System)

Kubernetes-native AI agent orchestration framework with A2A protocol support.

## Quick Reference

### Commit Guidelines
Use conventional commits: `feat(scope):`, `fix(scope):`, `refactor(scope):`, `test(scope):`, `docs:`

### Build & Test Commands
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

## RBAC (Important)
RBAC is auto-generated from `// +kubebuilder:rbac:` annotations.
- Controller RBAC: in controller files
- Leader election (leases, events): in `main.go`
- **Never manually edit** `config/rbac/role.yaml`

## Environment Variables

### Agent Runtime
| Variable | Description |
|----------|-------------|
| `AGENT_NAME` | Agent name (required) |
| `MODEL_API_URL` | LLM API URL (required) |
| `MODEL_NAME` | Model name (required) |
| `DEBUG_MOCK_RESPONSES` | Mock responses for testing |

### Operator (via ConfigMap)
| Variable | Description |
|----------|-------------|
| `DEFAULT_AGENT_IMAGE` | Default agent container image |
| `GATEWAY_API_ENABLED` | Enable Gateway API integration |

## Testing Notes

### E2E on macOS/KIND
MetalLB IPs (172.18.0.x) aren't accessible from host. Use:
```bash
kubectl port-forward -n envoy-gateway-system svc/envoy-gateway 8888:80 &
export GATEWAY_URL=http://localhost:8888
```

### Deterministic Testing
Use `DEBUG_MOCK_RESPONSES` env var for deterministic E2E tests:
```yaml
env:
- name: DEBUG_MOCK_RESPONSES
  value: '["Response 1", "Response 2"]'
```

## Domain-Specific Instructions
Detailed instructions are in `.github/instructions/`:
- `e2e.instructions.md`: E2E test environment and patterns
- `python.instructions.md`: Python framework details
- `operator.instructions.md`: Go operator development
