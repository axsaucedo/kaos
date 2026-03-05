# pctx-codemode MCP Server Runtime

Unified MCP aggregator with Code Mode based on [pctx](https://github.com/portofcontext/pctx).

## Overview

pctx aggregates multiple upstream MCP servers into a single unified interface, providing:
- **Code Mode**: Tools exposed as TypeScript functions in a sandboxed Deno environment
- **Token Efficiency**: 98.7% reduction in tokens for multi-step operations
- **Unified Auth**: Centralized authentication management for upstream servers

## Configuration

The server is configured via `spec.params` containing a JSON config (written to `pctx.json`):

```yaml
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: unified-mcp
spec:
  runtime: pctx-codemode
  params: |
    {
      "name": "unified-mcp",
      "version": "1.0.0",
      "servers": [
        {
          "name": "echo",
          "url": "http://mcpserver-echo.default.svc.cluster.local:8000/mcp"
        },
        {
          "name": "kubernetes",
          "url": "http://mcpserver-k8s.default.svc.cluster.local:8000/mcp"
        }
      ]
    }
```

## Config Structure

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Name of your unified MCP server |
| `version` | string | Yes | Version string |
| `servers` | array | Yes | List of upstream MCP servers |

### Server Entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier (becomes TypeScript namespace) |
| `url` | string | Yes | HTTP(S) URL of the MCP server endpoint |
| `auth` | object | No | Authentication config (see below) |

### Authentication

Bearer token:
```json
{
  "name": "secure-server",
  "url": "https://mcp.example.com",
  "auth": {
    "type": "bearer",
    "token": "${env:API_TOKEN}"
  }
}
```

Custom headers:
```json
{
  "name": "api-server",
  "url": "https://mcp.example.com",
  "auth": {
    "type": "headers",
    "headers": {
      "x-api-key": "${env:API_KEY}"
    }
  }
}
```

## How Code Mode Works

Instead of sequential tool calling:
```
Agent calls getSheet(id) → Server returns 1000 rows → Agent context
Agent calls filterRows(criteria) → Server returns 50 rows → Agent context
```

With Code Mode:
```typescript
const sheet = await gdrive.getSheet({ sheetId: "abc" });
const orders = sheet.filter((row) => row.status === "pending");
console.log(`Found ${orders.length} orders`);
```

This executes in a sandboxed Deno environment, dramatically reducing context window usage.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PCTX_CONFIG` | JSON config (set automatically from `spec.params`) |

## Local Testing

```bash
docker build -t pctx-test .
docker run -p 8000:8000 -e PCTX_CONFIG='{"name":"test","version":"1.0.0","servers":[]}' pctx-test
```

## References

- [pctx GitHub](https://github.com/portofcontext/pctx)
- [pctx Config Guide](https://github.com/portofcontext/pctx/blob/main/docs/config.md)
- [Code Mode Explained](https://www.anthropic.com/engineering/code-execution-with-mcp)
