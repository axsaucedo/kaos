---
applyTo: "operator/tests/**"
---

# E2E Test Instructions

## Environment Setup

E2E tests use pytest and require a Kubernetes cluster with Gateway API.

The test environment and cluster is configured with the following command:

```
make kind-create
make kind-e2e-run-tests # Also runs kind-load-images kind-e2e-install-kaos targets
```

### Quick Reference

Run `source .venv/bin/activate && <command>` for any relevant command.

To run tests directly against an already set up cluster:

```bash
cd operator/tests
source .venv/bin/activate
make e2e-test
```


To run sequentially:

```
cd operator/tests
source .venv/bin/activate
make e2e-test
```

To run a specific test (this is preferred when locally):

```
cd operator/tests
source .venv/bin/activate
python e2e/test_agent.py -v -k "test_agent_creation"  # Run single test
```

WHen looking to run all tests, it is preferrable to do it through creating a PR and committing the change and listening to the job.

The e2e tests in the CI take the following time in average:

* These are three: 1) core, 2) mcp, and 3) multi-agent
* These last 6-7min end to end
* These are part of the reusable-tests.yaml github action

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

### Important actions

* When finding important new learnings on common issues update this file.
* Keep this file succinct and functional

