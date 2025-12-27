# End-to-End Tests for Agentic Kubernetes Operator

These tests validate the complete operator workflow by deploying resources to a Kubernetes cluster.

## Prerequisites

1. **Kubernetes cluster** running and accessible via kubectl (default: docker-desktop context)
   ```bash
   kubectl cluster-info
   kubectl config current-context  # Should be docker-desktop
   ```

2. **Ollama** running on the host machine with SmolLM2-135M model
   ```bash
   ollama serve
   # In another terminal:
   ollama pull smollm2:135m
   ```

3. **Operator** deployed to the cluster
   ```bash
   cd operator/
   make docker-build-operator
   make deploy
   kubectl get pods -n agentic-system
   ```

4. **Agent runtime image** built and available to Kubernetes
   ```bash
   cd agent/
   make docker-build IMG=agentic-runtime:latest
   # For Docker Desktop, the image is automatically available
   ```

5. **Python dependencies** installed
   ```bash
   pip install -r requirements.txt
   ```

## Running Tests

### Run all E2E tests
```bash
pytest test_echo_agent_e2e.py -v
```

### Run specific test
```bash
pytest test_echo_agent_e2e.py::test_echo_agent_full_deployment -v -s
```

### Run with detailed logging
```bash
pytest test_echo_agent_e2e.py -v -s --log-cli-level=INFO
```

## Manual Deployment (for verification)

Before running automated tests, you can manually deploy resources to verify the operator works:

### 1. Create test namespace
```bash
kubectl create namespace test-e2e
```

### 2. Create ModelAPI resource
```yaml
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: ollama-proxy
  namespace: test-e2e
spec:
  mode: Proxy
  proxyConfig:
    env:
    - name: OPENAI_API_KEY
      value: "sk-test"
    - name: LITELLM_LOG
      value: "WARN"
    - name: LITELLM_MODEL_LIST
      value: "ollama/smollm2:135m"
    - name: OLLAMA_BASE_URL
      value: "http://host.docker.internal:11434"
```

Apply:
```bash
kubectl apply -f modelapi.yaml
kubectl get modelapi -n test-e2e
kubectl get deployment -n test-e2e
```

### 3. Create MCPServer resource
```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: echo-server
  namespace: test-e2e
spec:
  type: python-runtime
  config:
    mcp: "test-mcp-echo-server"
    env:
    - name: LOG_LEVEL
      value: "INFO"
  resources:
    requests:
      memory: "128Mi"
      cpu: "100m"
    limits:
      memory: "256Mi"
      cpu: "500m"
```

Apply:
```bash
kubectl apply -f mcpserver.yaml
kubectl get mcpserver -n test-e2e
kubectl get deployment -n test-e2e
```

### 4. Create Agent resource
```yaml
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: echo-agent
  namespace: test-e2e
spec:
  modelAPI: ollama-proxy
  mcpServers:
  - echo-server
  config:
    description: "E2E test echo agent"
    instructions: |
      You are a helpful test assistant.
      You have access to an echo tool for testing.
    env:
    - name: AGENT_LOG_LEVEL
      value: "INFO"
    - name: MODEL_NAME
      value: "smollm2:135m"
  agentNetwork:
    expose: true
    access: []
  replicas: 1
  resources:
    requests:
      memory: "256Mi"
      cpu: "200m"
    limits:
      memory: "512Mi"
      cpu: "1000m"
```

Apply:
```bash
kubectl apply -f agent.yaml
kubectl get agent -n test-e2e
kubectl get deployment -n test-e2e
```

### 5. Wait for deployments
```bash
kubectl rollout status deployment/modelapi-ollama-proxy -n test-e2e
kubectl rollout status deployment/mcpserver-echo-server -n test-e2e
kubectl rollout status deployment/agent-echo-agent -n test-e2e
```

### 6. Check pod logs
```bash
# ModelAPI logs
kubectl logs -f deployment/modelapi-ollama-proxy -n test-e2e

# MCPServer logs
kubectl logs -f deployment/mcpserver-echo-server -n test-e2e

# Agent logs
kubectl logs -f deployment/agent-echo-agent -n test-e2e
```

### 7. Port-forward to agent service
```bash
kubectl port-forward svc/agent-echo-agent 8000:8000 -n test-e2e
```

### 8. Test agent endpoints
```bash
# In another terminal:
curl http://localhost:8000/ready
curl http://localhost:8000/health
curl http://localhost:8000/agent/card
```

### 9. Cleanup
```bash
kubectl delete namespace test-e2e
```

## Test Structure

### test_echo_agent_full_deployment
- Creates all three resources (ModelAPI, MCPServer, Agent)
- Waits for all deployments to be ready
- Tests agent endpoints via HTTP port-forward
- Validates agent card and tool discovery

### test_echo_agent_invoke_task
- Creates all three resources
- Waits for readiness
- Invokes agent with a task (requires Ollama access)

### test_modelapi_deployment
- Tests ModelAPI resource creation independently
- Validates LiteLLM proxy is running

### test_mcpserver_deployment
- Tests MCPServer resource creation independently
- Validates MCP server is running

## Troubleshooting

### "Cannot connect to kubeconfig"
Ensure kubectl is configured and can access the cluster:
```bash
kubectl config view
kubectl get nodes
```

### "Deployment did not become ready"
Check pod status and logs:
```bash
kubectl describe pod <pod-name> -n test-e2e
kubectl logs <pod-name> -n test-e2e
```

### "Port-forward connection refused"
- Ensure port is not already in use: `lsof -i :18000`
- Wait longer for service to be created: `kubectl get svc -n test-e2e`
- Check service endpoints: `kubectl get endpoints -n test-e2e`

### "Agent can't reach Ollama/ModelAPI"
For Docker Desktop, resources on the host should be accessible via `host.docker.internal`:
```bash
# Inside a pod in the cluster:
curl http://host.docker.internal:11434/api/tags  # Ollama
```

### "MCP server not finding echo tool"
The test-mcp-echo-server must be installed. Check pod logs:
```bash
kubectl logs deployment/mcpserver-echo-server -n test-e2e
```

Should see: "test-mcp-echo-server started successfully"

## Notes

- Tests automatically create and clean up namespaces
- Each test run uses a unique namespace: `test-e2e-{timestamp}`
- Port-forward processes are cleaned up after tests complete
- Tests require pytest-asyncio for async HTTP calls
