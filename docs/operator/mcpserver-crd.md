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
  # Required: Runtime identifier
  # Use a registered runtime (python-string, kubernetes, slack) or "custom"
  runtime: python-string
  
  # Optional: Runtime-specific parameters
  # Passed to container via runtime's paramsEnvVar (e.g., MCP_TOOLS_STRING for python-string)
  params: |
    def echo(text: str) -> str:
        """Echo the input text."""
        return f"Echo: {text}"
  
  # Optional: ServiceAccount for RBAC (e.g., kubernetes runtime)
  serviceAccountName: my-mcp-sa
  
  # Optional: Container overrides
  container:
    image: my-custom-image:v1  # Required for "custom" runtime
    env:
    - name: LOG_LEVEL
      value: "INFO"
    resources:
      requests:
        memory: "128Mi"
        cpu: "100m"
  
  # Optional: Full PodSpec override
  podSpec:
    nodeSelector:
      gpu: "true"

status:
  phase: Ready           # Pending, Ready, Failed
  ready: true
  endpoint: "http://mcpserver-my-mcp.my-namespace.svc.cluster.local:8000"
  availableTools:
  - "echo"
  message: ""
```

## Spec Fields

### runtime (required)

Runtime identifier for the MCP server. Can be:

| Value | Description |
|-------|-------------|
| `python-string` | Python code execution via MCP_TOOLS_STRING |
| `kubernetes` | Kubernetes CRUD operations |
| `slack` | Slack integration |
| `custom` | User-provided container image |

Additional runtimes can be registered via the `kaos-mcp-runtimes` ConfigMap.

### params (optional)

Runtime-specific configuration passed to the container. The delivery method depends on the runtime:

| Runtime | Params Environment Variable |
|---------|---------------------------|
| `python-string` | `MCP_TOOLS_STRING` |
| `kubernetes` | `MCP_PARAMS` |
| `slack` | `MCP_PARAMS` |

#### python-string params

For the python-string runtime, define Python functions inline:

```yaml
spec:
  runtime: python-string
  params: |
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

**Security Note:** python-string uses `exec()` to define functions. Only use with trusted input.

### serviceAccountName (optional)

ServiceAccount for the MCPServer pod. Required for runtimes that need Kubernetes API access (e.g., kubernetes runtime).

Create RBAC using:
```bash
kaos system create-rbac --name my-mcp-sa --namespace my-namespace
```

### container (optional)

Override container configuration. For "custom" runtime, `container.image` is required.

```yaml
spec:
  runtime: custom
  container:
    image: my-mcp-server:v1
    env:
    - name: API_KEY
      valueFrom:
        secretKeyRef:
          name: mcp-secrets
          key: api-key
    resources:
      requests:
        memory: "256Mi"
        cpu: "100m"
```

### podSpec (optional)

Override the generated pod spec using Kubernetes strategic merge patch.

### gatewayRoute (optional)

Configure Gateway API routing, including request timeout:

```yaml
spec:
  gatewayRoute:
    timeout: "30s"  # Default for MCPServer
```

## Available Runtimes

### python-string

Execute Python functions defined in params.

```yaml
spec:
  runtime: python-string
  params: |
    def echo(message: str) -> str:
        """Echo back the message."""
        return f"Echo: {message}"
```

### kubernetes

Kubernetes CRUD operations. Requires serviceAccountName with appropriate RBAC.

```yaml
spec:
  runtime: kubernetes
  serviceAccountName: k8s-mcp-sa
```

### slack

Slack integration. Configure via container environment variables.

```yaml
spec:
  runtime: slack
  container:
    env:
    - name: SLACK_BOT_TOKEN
      valueFrom:
        secretKeyRef:
          name: slack-secrets
          key: bot-token
```

### custom

User-provided MCP server image. Must expose HTTP on port 8000.

```yaml
spec:
  runtime: custom
  container:
    image: my-mcp-server:v1
```

## Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current phase: Pending, Ready, Failed |
| `ready` | bool | Whether server is ready |
| `endpoint` | string | Service URL for agents |
| `availableTools` | []string | List of tool names |
| `message` | string | Additional status info |
| `deployment` | object | Deployment status |

## Examples

### Echo Tool (python-string)

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: echo-tools
spec:
  runtime: python-string
  params: |
    def echo(message: str) -> str:
        """Echo the message back."""
        return f"Echo: {message}"
```

### Calculator (python-string)

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: calculator
spec:
  runtime: python-string
  params: |
    def add(a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b
    
    def subtract(a: int, b: int) -> int:
        """Subtract b from a."""
        return a - b
```

### Kubernetes CRUD

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: k8s-tools
spec:
  runtime: kubernetes
  serviceAccountName: k8s-mcp-sa
```

### Custom MCP Server

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: my-custom
spec:
  runtime: custom
  container:
    image: ghcr.io/myorg/my-mcp-server:v1
    env:
    - name: API_KEY
      valueFrom:
        secretKeyRef:
          name: api-secrets
          key: key
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
  model: gpt-4
  mcpServers:
  - echo-tools
  - calculator
  config:
    instructions: |
      You have access to echo and calculator tools.
```

## CLI Commands

```bash
# List MCPServers
kaos mcp list

# Deploy from YAML
kaos mcp deploy mcpserver.yaml

# Deploy custom image directly
kaos mcp deploy --name my-mcp --image my-image:v1

# Deploy registered runtime
kaos mcp deploy --name my-mcp --runtime slack

# Get details
kaos mcp get my-mcp

# View logs
kaos mcp logs my-mcp

# Invoke a tool
kaos mcp invoke my-mcp --tool echo --args '{"message": "hello"}'

# Delete
kaos mcp delete my-mcp
```

## Creating Custom MCP Servers

Use the CLI to scaffold and build custom MCP servers:

```bash
# Initialize project
kaos mcp init my-server

# Edit server.py with your tools

# Build image
kaos mcp build --name my-server --tag v1

# Load to KIND (for local testing)
kaos mcp build --name my-server --tag v1 --kind-load

# Deploy
kaos mcp deploy --name my-server --image my-server:v1
```

## Troubleshooting

### MCPServer CrashLoopBackOff

Check pod logs:
```bash
kaos mcp logs my-mcp
```

Common causes:
- Invalid Python syntax in params
- Missing serviceAccountName for kubernetes runtime
- Image pull errors for custom runtime

### Tools Not Discovered

Verify MCPServer is Ready:
```bash
kaos mcp get my-mcp
```

### RBAC Errors (kubernetes runtime)

Create appropriate permissions:
```bash
kaos system create-rbac --name my-mcp-sa --namespace my-ns
kubectl apply -f rbac.yaml
```
