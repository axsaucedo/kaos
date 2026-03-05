# FastMCP Code Mode Server

MCP server aggregator that connects to multiple upstream KAOS MCP servers and wraps them with FastMCP's [CodeMode](https://gofastmcp.com/servers/transforms/code-mode) transform. Instead of exposing individual tools from each upstream server, it provides meta-tools (`search`, `get_schema`, `execute`) that let LLMs discover and chain cross-server tool calls via Python code execution in a sandbox.

## How It Works

1. JSON config listing upstream MCP server URLs is loaded from `MCP_SERVERS_CONFIG`
2. Each upstream server is mounted as a proxy with a namespace prefix
3. CodeMode transform wraps all aggregated tools into 3 meta-tools
4. The LLM writes Python code calling `await call_tool("namespace_tool", params)` to chain operations

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MCP_SERVERS_CONFIG` | JSON config with upstream server URLs |

## Configuration Format

```json
{
  "servers": [
    {"name": "calc", "url": "http://mcpserver-calculator:8000/mcp"},
    {"name": "text", "url": "http://mcpserver-textutils:8000/mcp"}
  ]
}
```

Tools from each server are namespaced: `calc_add`, `calc_multiply`, `text_uppercase`, etc.

## KAOS Integration

Deploy as a KAOS MCPServer with runtime `fastmcp-codemode`:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: my-gateway
spec:
  runtime: fastmcp-codemode
  params: |
    {
      "servers": [
        {"name": "calc", "url": "http://mcpserver-calculator:8000/mcp"},
        {"name": "text", "url": "http://mcpserver-textutils:8000/mcp"}
      ]
    }
```
