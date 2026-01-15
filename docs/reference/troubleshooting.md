# Troubleshooting Guide

Common issues and solutions for the KAOS.

## Agent Issues

### Agent Stuck in Pending Phase

**Symptoms:** Agent status shows `phase: Pending` or `phase: Waiting`

**Diagnosis:**
```bash
kubectl describe agent my-agent -n my-namespace
kubectl get modelapi,mcpserver -n my-namespace
```

**Common Causes:**

1. **ModelAPI not ready**
   ```bash
   kubectl get modelapi -n my-namespace
   # If not Ready, check ModelAPI troubleshooting section
   ```

2. **MCPServer not ready**
   ```bash
   kubectl get mcpserver -n my-namespace
   # If not Ready, check MCPServer troubleshooting section
   ```

3. **Peer agent not ready**
   ```bash
   kubectl get agent -n my-namespace
   # Agents in agentNetwork.access must be Ready first
   ```

### Agent Pod CrashLoopBackOff

**Diagnosis:**
```bash
kubectl logs -l app=my-agent -n my-namespace
kubectl describe pod -l app=my-agent -n my-namespace
```

**Common Causes:**

1. **Invalid MODEL_API_URL**
   - Check if ModelAPI service exists
   - Verify endpoint is reachable

2. **Image not found**
   - Ensure `kaos-agent:latest` is available
   - For remote clusters, push to registry

3. **Python errors**
   - Check agent server startup logs

### Agent Returns Errors

**Diagnosis:**
```bash
# Check agent logs
kubectl logs -l app=my-agent -n my-namespace -f

# Check memory events
kubectl port-forward svc/my-agent 8000:80 -n my-namespace
curl http://localhost:8000/memory/events | jq
```

**Common Causes:**

1. **LLM connection failed**
   - Verify MODEL_API_URL is correct
   - Check ModelAPI is responding

2. **Tool execution failed**
   - Check MCPServer logs
   - Verify tool arguments are valid

3. **Delegation failed**
   - Check peer agent is accessible
   - Verify peer agent name matches exactly

## ModelAPI Issues

### ModelAPI Stuck in Pending

**Diagnosis:**
```bash
kubectl describe modelapi my-modelapi -n my-namespace
kubectl get pods -l app=my-modelapi -n my-namespace
```

**Common Causes:**

1. **Image pull error**
   ```bash
   kubectl describe pod -l app=my-modelapi -n my-namespace | grep -A5 "Events:"
   ```

2. **Insufficient resources**
   - Hosted mode requires significant memory for models
   - Increase resource limits

3. **Model download in progress (Hosted mode)**
   - Large models can take 10+ minutes to download
   - Check logs for download progress:
   ```bash
   kubectl logs -l app=my-modelapi -n my-namespace
   ```

### Proxy Mode Not Connecting to Backend

**Diagnosis:**
```bash
# Check LiteLLM logs
kubectl logs -l app=my-modelapi -n my-namespace

# Test connectivity from inside cluster
kubectl exec -it deploy/my-agent -n my-namespace -- \
  curl http://my-modelapi:8000/health
```

**Common Causes:**

1. **Wrong apiBase URL**
   - For Docker Desktop: use `http://host.docker.internal:<port>`
   - For in-cluster: use service name

2. **Backend not running**
   - Verify Ollama/OpenAI is accessible

3. **Firewall blocking connection**
   - Check network policies

### Hosted Mode Model Not Available

**Diagnosis:**
```bash
kubectl logs -l app=my-modelapi -n my-namespace
```

**Common Causes:**

1. **Model name incorrect**
   - Use exact Ollama model name (e.g., `smollm2:135m`)

2. **Insufficient disk space**
   - Models require disk space for download

3. **Download timeout**
   - Large models may timeout; check readiness probe settings

## MCPServer Issues

### MCPServer CrashLoopBackOff

**Diagnosis:**
```bash
kubectl logs -l app=my-mcp -n my-namespace
kubectl describe pod -l app=my-mcp -n my-namespace
```

**Common Causes:**

1. **Invalid toolsString syntax**
   - Test Python code locally first
   - Check for syntax errors in logs

2. **Package not found (mcp option)**
   - Verify PyPI package name is correct
   - Package must implement MCP protocol

3. **Missing dependencies**
   - For toolsString, only standard library is available
   - Use `mcp` option for complex dependencies

### Tools Not Discovered by Agent

**Diagnosis:**
```bash
# Check MCPServer is ready
kubectl get mcpserver my-mcp -n my-namespace

# Test tools endpoint
kubectl exec -it deploy/my-agent -n my-namespace -- \
  curl http://my-mcp/mcp/tools
```

**Common Causes:**

1. **MCPServer not referenced in Agent**
   ```yaml
   spec:
     mcpServers:
     - my-mcp  # Must be listed here
   ```

2. **Tool discovery failed**
   - Check MCPClient initialization in agent logs

3. **Tools not enabled**
   ```yaml
   config:
     agenticLoop:
       enableTools: true  # Must be true
   ```

## Operator Issues

### Operator Not Starting

**Diagnosis:**
```bash
kubectl logs -n kaos-system deployment/kaos-operator-controller-manager
```

**Common Causes:**

1. **RBAC permissions missing**
   - Leases permission required for leader election
   - Check `role.yaml` includes leases and events

2. **CRDs not installed**
   ```bash
   kubectl get crds | grep kaos.tools
   ```

3. **Image not available**
   - Check operator image is pullable

### Resources Not Reconciling

**Diagnosis:**
```bash
kubectl logs -n kaos-system deployment/kaos-operator-controller-manager -f
```

**Common Causes:**

1. **Operator not running**
   ```bash
   kubectl get pods -n kaos-system
   ```

2. **Watch error**
   - Check for permission errors in logs
   - Verify RBAC is correctly applied

3. **Panic/crash**
   - Check logs for stack traces
   - Report bugs with reproduction steps

## Multi-Agent Issues

### Delegation Not Working

**Diagnosis:**
```bash
# Check coordinator memory
kubectl port-forward svc/coordinator 8000:80 -n my-namespace
curl http://localhost:8000/memory/events | jq '.events[] | select(.event_type | contains("delegation"))'
```

**Common Causes:**

1. **Peer agent not in access list**
   ```yaml
   agentNetwork:
     access:
     - worker-1  # Must list all delegatable agents
   ```

2. **Peer agent service not exposed**
   ```yaml
   agentNetwork:
     expose: true  # Required for peer agents
   ```

3. **Delegation disabled**
   ```yaml
   config:
     agenticLoop:
       enableDelegation: true  # Must be true
   ```

4. **Agent name mismatch**
   - Name in delegation must match exactly

### Delegation Timeout

**Common Causes:**

1. **Peer agent slow to respond**
   - Increase timeout in RemoteAgent

2. **Network issues**
   - Check service connectivity

3. **Peer agent overloaded**
   - Scale peer agents or add replicas

## Performance Issues

### Slow Response Times

**Diagnosis:**
```bash
# Check which step is slow
kubectl logs -l app=my-agent -n my-namespace | grep -i "step\|time"
```

**Common Causes:**

1. **Model too slow**
   - Use smaller model for faster inference
   - Consider GPU acceleration

2. **Too many agentic loop steps**
   - Reduce `maxSteps` if appropriate
   - Improve instructions to reduce iterations

3. **Tool execution slow**
   - Optimize tool implementations
   - Add caching if appropriate

### Memory Issues

**Diagnosis:**
```bash
kubectl top pods -n my-namespace
```

**Common Causes:**

1. **Too many sessions**
   - Sessions accumulate in memory
   - Consider periodic cleanup

2. **Large model in Hosted mode**
   - Increase memory limits
   - Use smaller model
