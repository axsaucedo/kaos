# FastMCP Code Mode Server

MCP server that wraps Python tool functions with FastMCP's [CodeMode](https://gofastmcp.com/servers/transforms/code-mode) transform. Instead of exposing individual tools, it provides meta-tools (`search`, `get_schema`, `execute`) that let LLMs discover and chain tool calls via Python code execution in a sandbox.

## How It Works

1. Python functions are loaded from the `MCP_TOOLS_STRING` environment variable
2. Functions are registered as tools on a FastMCP server with CodeMode transform
3. Clients see meta-tools instead of individual tool schemas
4. The LLM writes Python code that calls `await call_tool(name, params)` to chain operations

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MCP_TOOLS_STRING` | Python function definitions to expose as tools |

## Usage

```bash
export MCP_TOOLS_STRING='
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def multiply(x: int, y: int) -> int:
    """Multiply two numbers."""
    return x * y
'

python server.py
```

## KAOS Integration

Deploy as a KAOS MCPServer with runtime `fastmcp-codemode`:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: my-codemode-server
spec:
  runtime: fastmcp-codemode
  params: |
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
```
