# MCP Server Wrapper

This component provides a simple HTTP wrapper for MCP (Model Context Protocol) servers.

## Philosophy

Rather than implementing MCP servers ourselves, we use **externally-maintained, proven packages** to:
- Reduce maintenance burden
- Leverage community-reviewed implementations
- Ensure security through well-audited packages
- Simplify operations (fewer Docker images to manage)

## Supported Servers

### Calculator (Default)
- **Package**: `mcp-server-calculator`
- **Install**: `pip install mcp-server-calculator`
- **Operations**: Basic arithmetic (add, subtract, multiply, divide, etc.)
- **License**: MIT
- **Safety**: ✅ No external dependencies, pure computation only

### Adding More Servers

To add new servers, follow this pattern:

1. **Update `pyproject.toml`**:
   ```toml
   dependencies = [
       "mcp-server-calculator>=0.1.0",
       "mcp-server-new>=0.1.0",  # Add here
   ]
   ```

2. **Update `loader.py` SAFE_SERVERS registry**:
   ```python
   SAFE_SERVERS = {
       "calculator": "mcp_server_calculator",
       "new": "mcp_server_new",  # Add here
   }
   ```

3. **Environment variable** to use:
   ```bash
   MCP_SERVERS=calculator,new
   ```

## Security Requirements

Before adding a new server:
1. ✅ It's from a trusted source (official organization or well-known maintainer)
2. ✅ MIT or compatible license
3. ✅ It's been community-reviewed
4. ✅ No known vulnerabilities
5. ✅ No suspicious dependencies or network calls

## Usage

### Local Development

```bash
# Install dependencies
uv pip install -e .

# Run the MCP server wrapper (default: calculator)
python -m uvicorn loader:app --host 0.0.0.0 --port 9000

# Get available tools
curl http://localhost:9000/tools

# Execute a tool
curl -X POST http://localhost:9000/tools/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name": "calculator.add", "input": {"a": 2, "b": 3}}'
```

### Docker

```bash
# Build
docker build -t agentic-mcp-servers:latest .

# Run
docker run -e MCP_SERVERS=calculator \
  -p 9000:9000 \
  agentic-mcp-servers:latest
```

### Kubernetes

```yaml
apiVersion: agentic.example.com/v1alpha1
kind: MCPServer
metadata:
  name: calculator
spec:
  type: python-runtime
  config:
    mcp: "calculator"
```

## API Endpoints

- `GET /health` - Health check
- `GET /servers` - List enabled servers
- `GET /tools` - List all tools from all servers
- `GET /servers/{name}/tools` - List tools from specific server
- `POST /tools/execute` - Execute a tool

## Notes

The MCP server wrapper is stateless and can scale horizontally. Each deployment will load and cache the specified servers.
