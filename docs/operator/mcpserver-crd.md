# MCPServer CRD

The MCPServer custom resource deploys MCP (Model Context Protocol) tool servers that agents can use.

## Full Specification

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: my-mcp
  namespace: my-namespace
spec:
  # Required: Runtime type
  type: python-runtime  # or node-runtime (future)
  
  # Required: Server configuration
  config:
    # Tools configuration (one of the following)
    tools:
      # Option 1: PyPI package name
      fromPackage: "test-mcp-echo-server"
      
      # Option 2: Dynamic Python tools defined inline
      fromString: |
        def echo(text: str) -> str:
            """Echo the input text."""
            return f"Echo: {text}"
        
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
      
      # Option 3: Tools from a Secret
      fromSecretKeyRef:
        name: my-tools-secret
        key: tools.py
    
    # Environment variables
    env:
    - name: LOG_LEVEL
      value: "INFO"
  
  # Optional: PodSpec override using strategic merge patch
  podSpec:
    containers:
    - name: mcp-server  # Must match generated container name
      resources:
        requests:
          memory: "128Mi"
          cpu: "100m"
        limits:
          memory: "256Mi"
          cpu: "500m"

status:
  phase: Ready           # Pending, Ready, Failed
  ready: true
  endpoint: "http://mcpserver-my-mcp.my-namespace.svc.cluster.local:8000"
  availableTools:
  - "echo"
  - "add"
  message: ""
```

## Spec Fields

### type (required)

Runtime type for the MCP server:

| Value | Description |
|-------|-------------|
| `python-runtime` | Python-based MCP server |
| `node-runtime` | Node.js-based (future) |

### config (required)

#### config.tools

Tools configuration - use one of the following options:

##### tools.fromPackage

PyPI package name to run as MCP server:

```yaml
config:
  tools:
    fromPackage: "test-mcp-echo-server"
```

The package is installed via pip and executed. It must expose MCP-compatible endpoints.

##### tools.fromString

Dynamic Python tools defined inline:

```yaml
config:
  tools:
    fromString: |
      def greet(name: str) -> str:
          """Greet a person by name."""
          return f"Hello, {name}!"
      
      def calculate(expression: str) -> str:
          """Evaluate a math expression."""
          try:
              return str(eval(expression))
          except Exception as e:
              return f"Error: {e}"
```

**Requirements:**
- Functions must have type annotations
- Functions must have docstrings (used as descriptions)
- Supported types: `str`, `int`, `dict`, `list`

**Security Note:** `fromString` uses `exec()` to define functions. Only use with trusted input.

##### tools.fromSecretKeyRef

Load tools from a Kubernetes Secret:

```yaml
config:
  tools:
    fromSecretKeyRef:
      name: my-tools-secret
      key: tools.py
```

#### config.env

Environment variables for the MCP server:

```yaml
config:
  env:
  - name: LOG_LEVEL
    value: "DEBUG"
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: mcp-secrets
        key: api-key
```

### podSpec (optional)

Override the generated pod spec using Kubernetes strategic merge patch.

```yaml
spec:
  podSpec:
    containers:
    - name: mcp-server  # Must match the generated container name
      resources:
        requests:
          memory: "256Mi"
          cpu: "100m"
```

### gatewayRoute (optional)

Configure Gateway API routing, including request timeout:

```yaml
spec:
  gatewayRoute:
    # Request timeout for the HTTPRoute (Gateway API Duration format)
    # Default: "30s" for MCPServer (tool calls are typically fast)
    # Set to "0s" to use Gateway's default timeout
    timeout: "30s"
```

## Container Images

| Tool Source | Image | Command |
|-------------|-------|---------|
| `tools.fromPackage` | `python:3.12-slim` | `pip install <package> && <package>` |
| `tools.fromString` | `kaos-agent:latest` | `python -m mcptools.server` |
| `tools.fromSecretKeyRef` | `kaos-agent:latest` | `python -m mcptools.server` |

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed |
| `ready` | bool | Whether server is ready |
| `endpoint` | string | Service URL for agents |
| `availableTools` | []string | List of tool names |
| `message` | string | Additional status info |
| `deployment` | object | Deployment status for rolling update visibility |

### deployment (status)

Mirrors key status fields from the underlying Kubernetes Deployment:

| Field | Type | Description |
|-------|------|-------------|
| `replicas` | int32 | Total number of non-terminated pods |
| `readyReplicas` | int32 | Number of pods with Ready condition |
| `availableReplicas` | int32 | Number of available pods |
| `updatedReplicas` | int32 | Number of pods with desired template (rolling update progress) |
| `conditions` | array | Deployment conditions (Available, Progressing, ReplicaFailure) |

## Examples

### Echo Tool (PyPI Package)

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
spec:
  type: python-runtime
  config:
    tools:
      fromPackage: "test-mcp-echo-server"
```

### Calculator Tool (Dynamic)

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: calculator
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        def add(a: int, b: int) -> int:
            """Add two numbers together."""
            return a + b
        
        def subtract(a: int, b: int) -> int:
            """Subtract b from a."""
            return a - b
        
        def multiply(a: int, b: int) -> int:
            """Multiply two numbers."""
            return a * b
        
        def divide(a: int, b: int) -> str:
            """Divide a by b."""
            if b == 0:
                return "Error: Division by zero"
            return str(a / b)
```

### String Utilities with Resources

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: string-utils
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        def uppercase(text: str) -> str:
            """Convert text to uppercase."""
            return text.upper()
        
        def lowercase(text: str) -> str:
            """Convert text to lowercase."""
            return text.lower()
        
        def reverse(text: str) -> str:
            """Reverse the text."""
            return text[::-1]
  podSpec:
    containers:
    - name: mcp-server
      resources:
        requests:
          memory: "128Mi"
```

### External API Tool with Secret

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: weather-api
spec:
  type: python-runtime
  config:
    tools:
      fromString: |
        import os
        import urllib.request
        import json
        
        def get_weather(city: str) -> str:
            """Get current weather for a city."""
            api_key = os.environ.get("WEATHER_API_KEY", "")
            url = f"https://api.weather.com/v1/current?city={city}&key={api_key}"
            try:
                with urllib.request.urlopen(url) as response:
                    data = json.loads(response.read())
                    return f"{city}: {data['temp']}°C, {data['conditions']}"
            except Exception as e:
                return f"Error: {e}"
    
    env:
    - name: WEATHER_API_KEY
      valueFrom:
        secretKeyRef:
          name: api-keys
          key: weather
```

## Integration with Agent

Reference MCPServer in Agent spec:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
spec:
  modelAPI: my-modelapi
  mcpServers:
  - echo-tools
  - calculator
  config:
    instructions: |
      You have access to echo and calculator tools.
      Use echo to repeat messages.
      Use calculator for math operations.
```

The operator:
1. Waits for MCPServers to be Ready (if `waitForDependencies: true`)
2. Sets `MCP_SERVERS=[echo-tools, calculator]`
3. Sets `MCP_SERVER_<NAME>_URL=http://mcpserver-<name>:8000`

## HTTP Endpoints

MCPServer exposes:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe |
| `/mcp/tools` | GET | List available tools |
| `/mcp/tools` | POST | Execute a tool |

### Tool Listing

```bash
curl http://mcpserver-my-mcp:8000/mcp/tools
```

### Tool Execution

```bash
curl -X POST http://mcpserver-my-mcp:8000/mcp/tools \
  -H "Content-Type: application/json" \
  -d '{"tool": "echo", "arguments": {"text": "Hello"}}'
```

## Troubleshooting

### MCPServer CrashLoopBackOff

Check pod logs:

```bash
kubectl logs -l mcpserver=my-mcp -n my-namespace
```

Common causes:
- Invalid `fromString` Python syntax
- Package not found (for `fromPackage` option)
- Missing dependencies

### Tools Not Discovered by Agent

Verify MCPServer is Ready:

```bash
kubectl get mcpserver my-mcp -n my-namespace
```

Test endpoint manually:

```bash
kubectl exec -it deploy/agent-my-agent -n my-namespace -- \
  curl http://mcpserver-my-mcp:8000/mcp/tools
```

### fromString Syntax Errors

Test your Python code locally:

```python
tools_string = '''
def my_tool(x: str) -> str:
    """My tool description."""
    return x
'''

namespace = {}
exec(tools_string, {}, namespace)
print(namespace)  # Should show your function
```
