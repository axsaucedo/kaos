# MCPServer CRD

The MCPServer custom resource deploys MCP (Model Context Protocol) tool servers that agents can use.

## Full Specification

```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: my-mcp
  namespace: my-namespace
spec:
  # Required: Runtime type
  type: python-runtime  # or node-runtime (future)
  
  # Required: Server configuration
  config:
    # Option 1: PyPI package name
    mcp: "test-mcp-echo-server"
    
    # Option 2: Dynamic Python tools
    toolsString: |
      def echo(text: str) -> str:
          """Echo the input text."""
          return f"Echo: {text}"
      
      def add(a: int, b: int) -> int:
          """Add two numbers."""
          return a + b
    
    # Environment variables
    env:
    - name: LOG_LEVEL
      value: "INFO"
  
  # Optional: Resource requirements
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
  endpoint: "http://my-mcp.my-namespace.svc.cluster.local"
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

#### config.mcp

PyPI package name to run as MCP server:

```yaml
config:
  mcp: "test-mcp-echo-server"
```

The package is installed via pip and executed. It must expose MCP-compatible endpoints.

Available packages:
- `test-mcp-echo-server` - Simple echo tool for testing
- Custom packages that implement MCP protocol

#### config.toolsString

Dynamic Python tools defined inline:

```yaml
config:
  toolsString: |
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

**Security Note:** `toolsString` uses `exec()` to define functions. Only use with trusted input.

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

### resources (optional)

Resource requirements:

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "1000m"
```

## Container Images

| Tool Source | Image | Command |
|-------------|-------|---------|
| `mcp` (package) | `python:3.12-slim` | `pip install <package> && uvx <package>` |
| `toolsString` | `agentic-agent:latest` | `python -m mcptools.server` |

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed |
| `ready` | bool | Whether server is ready |
| `endpoint` | string | Service URL for agents |
| `availableTools` | []string | List of tool names |
| `message` | string | Additional status info |

## Examples

### Echo Tool (PyPI Package)

```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
spec:
  type: python-runtime
  config:
    mcp: "test-mcp-echo-server"
```

### Calculator Tool (Dynamic)

```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: calculator
spec:
  type: python-runtime
  config:
    toolsString: |
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
  resources:
    requests:
      memory: "128Mi"
```

### String Utilities

```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: string-utils
spec:
  type: python-runtime
  config:
    toolsString: |
      def uppercase(text: str) -> str:
          """Convert text to uppercase."""
          return text.upper()
      
      def lowercase(text: str) -> str:
          """Convert text to lowercase."""
          return text.lower()
      
      def reverse(text: str) -> str:
          """Reverse the text."""
          return text[::-1]
      
      def word_count(text: str) -> int:
          """Count words in text."""
          return len(text.split())
```

### External API Tool

```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: weather-api
spec:
  type: python-runtime
  config:
    toolsString: |
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
apiVersion: ethical.institute/v1alpha1
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
1. Waits for MCPServers to be Ready
2. Sets `MCP_SERVERS=echo-tools,calculator`
3. Sets `MCP_SERVER_ECHO_TOOLS_URL=http://echo-tools:80`
4. Sets `MCP_SERVER_CALCULATOR_URL=http://calculator:80`

## HTTP Endpoints

MCPServer exposes:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe (includes tool list) |
| `/mcp/tools` | GET | List available tools |
| `/mcp/tools` | POST | Execute a tool |

### Tool Listing

```bash
curl http://my-mcp:80/mcp/tools
```

```json
{
  "tools": [
    {
      "name": "echo",
      "description": "Echo the input text.",
      "parameters": {
        "text": {"type": "string"}
      }
    }
  ]
}
```

### Tool Execution

```bash
curl -X POST http://my-mcp:80/mcp/tools \
  -H "Content-Type: application/json" \
  -d '{"tool": "echo", "arguments": {"text": "Hello"}}'
```

```json
{
  "result": "Echo: Hello"
}
```

## Troubleshooting

### MCPServer CrashLoopBackOff

Check pod logs:

```bash
kubectl logs -l app=my-mcp -n my-namespace
```

Common causes:
- Invalid `toolsString` Python syntax
- Package not found (for `mcp` option)
- Missing dependencies

### Tools Not Discovered by Agent

Verify MCPServer is Ready:

```bash
kubectl get mcpserver my-mcp -n my-namespace
```

Test endpoint manually:

```bash
kubectl exec -it deploy/my-agent -n my-namespace -- \
  curl http://my-mcp/mcp/tools
```

### toolsString Syntax Errors

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
