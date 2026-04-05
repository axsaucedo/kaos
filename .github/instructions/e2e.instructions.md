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

Or use kaos CLI directly:
```bash
# After creating KIND cluster and loading images
kaos system install --gateway-enabled --metallb-enabled --chart-path chart/ --wait
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
make kind-create                  # Creates cluster with Gateway API + MetalLB (uses kaos CLI)
make kind-load-images             # Build and load images
make kind-e2e-install-kaos        # Install operator via kaos CLI with Gateway API enabled
make e2e-test                     # Run E2E tests
```

### Test Structure
- `conftest.py`: Fixtures, namespace management, Gateway URL setup
- `test_a2a_e2e.py`: A2A JSON-RPC endpoint tests (SendMessage, GetTask, CancelTask)
- `test_autonomous_e2e.py`: Autonomous execution tests (A2A-triggered, budget enforcement, startup-activated)
- `test_agentic_loop_e2e.py`: Agent with MCP tools tests
- `test_mcp_tools_e2e.py`: MCPServer runtime tests (python-string)
- `test_modelapi_e2e.py`: ModelAPI CRD tests
- `test_multi_agent_e2e.py`: Multi-agent delegation tests
- `test_base_func_e2e.py`: Basic functionality tests
- `test_examples_e2e.py`: Example documentation execution tests (jupytext-based)

### CRD Patterns in Tests
MCPServer uses runtime-based architecture:
```yaml
spec:
  runtime: python-string
  params: |
    def tool_name(): ...
  container:
    env:
    - name: LOG_LEVEL
      value: DEBUG
```

Agent/ModelAPI use container.env for environment variables:
```yaml
spec:
  container:
    env:
    - name: LOG_LEVEL
      value: DEBUG
```

### Mock Response Patterns (DEBUG_MOCK_RESPONSES)

E2E tests use `DEBUG_MOCK_RESPONSES` env var. The framework uses Pydantic AI with native tool calling only (no string-mode concept). Delegation uses the same `delegate_to_` prefix.

**Important:** Pydantic AI needs 2 mock responses for tool calls (not 3 like the old framework). Existing tests with 3 entries still work — the extra entry is unused.

**Tool call (MCP tool):**
```json
[
  "{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"hello\"}}]}",
  "The echo tool returned the result."
]
```

**Delegation (sub-agent):**
```json
[
  "{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"delegate_to_worker-name\", \"arguments\": {\"task\": \"Process this\"}}]}",
  "The worker completed the task."
]
```

**Worker (plain text, no tools):**
```json
["Task completed by worker."]
```

**Legacy 3-entry format (still works):**
```json
[
  "{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"hello\"}}]}",
  "No more actions needed.",
  "The echo tool returned the result."
]
```
The 2nd entry becomes the output (Pydantic AI stops there), 3rd is ignored.

Note: Absence of `tool_calls` in a response signals loop completion. The old `{"tool": "name", ...}` single-tool format is NOT supported — always use `tool_calls` array.

**Autonomous (multi-iteration):**
Each autonomous iteration consumes mock responses sequentially. A 2-iteration run with 1 tool call:
```json
[
  "{\"tool_calls\": [{\"id\": \"call_1\", \"name\": \"echo\", \"arguments\": {\"message\": \"iteration 1\"}}]}",
  "Still working, need more iterations.",
  "Goal fully achieved. Final report."
]
```
Responses 1-2: iteration 1 (tool call + text with tools → continues). Response 3: iteration 2 (text only, no tools → loop ends).

**Autonomous CRD config (autonomous mode):**
```yaml
spec:
  config:
    autonomous:
      enabled: true
      goal: "Check system health"
      intervalSeconds: 10
      maxIterRuntimeSeconds: 60
```

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

