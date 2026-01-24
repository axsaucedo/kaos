---
applyTo: "operator/tests/**"
---

# E2E Test Instructions

## Environment Setup

E2E tests use pytest and require a Kubernetes cluster with Gateway API.

### Quick Reference
```bash
cd operator/tests
source .venv/bin/activate
pytest e2e/ -v                    # Run all E2E tests (parallel)
pytest e2e/ -v --sequential       # Run sequentially with debug output
pytest e2e/test_agent.py -v -k "test_agent_creation"  # Run single test
```

### Required Environment Variables
- `GATEWAY_URL`: URL for the Gateway (default: `http://localhost:80`)
- `OPERATOR_MANAGED_EXTERNALLY`: Set to `1` to skip operator reinstall
- `HELM_VALUES_FILE`: Path to Helm values file

### macOS/KIND Specifics
MetalLB IPs (172.18.0.x) are NOT accessible from macOS host. Use port-forward:
```bash
kubectl port-forward -n envoy-gateway-system svc/envoy-gateway 8888:80 &
export GATEWAY_URL=http://localhost:8888
export OPERATOR_MANAGED_EXTERNALLY=1
```

### KIND Cluster Setup
```bash
cd operator
make kind-create                  # Creates cluster with Gateway API + MetalLB
make kind-load-images             # Build and load images
make kind-e2e-install-kaos        # Install operator via Helm
make e2e-test                     # Run E2E tests
```

### Test Structure
- `conftest.py`: Fixtures, namespace management, Gateway URL setup
- `test_agent.py`: Agent CRD tests
- `test_mcpserver.py`: MCPServer CRD tests  
- `test_modelapi.py`: ModelAPI CRD tests
- `test_multi_agent.py`: Multi-agent delegation tests

### Key Patterns
- Tests create unique namespaces per session
- `wait_for_ready()` helper waits for resource Ready status
- Tests use `apply_yaml()` to create resources from YAML strings
- CRDs use `kubectl apply --server-side` due to large CRD size (~580KB)

### Common Issues
1. **Timeout errors**: Increase `PYTEST_TIMEOUT` or use `--timeout=300`
2. **Gateway 503**: Wait for Gateway pods: `kubectl wait --for=condition=available deployment -n envoy-gateway-system --all`
3. **CRD not found**: Ensure `make kind-e2e-install-kaos` completed successfully
