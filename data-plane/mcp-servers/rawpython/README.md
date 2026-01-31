# RawPython MCP Server

A simple MCP server that loads Python functions from an environment variable and exposes them as MCP tools.

## Usage

Set the `MCP_TOOLS_STRING` environment variable with Python function definitions:

```bash
export MCP_TOOLS_STRING='
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'
```

Run the server:
```bash
fastmcp run server:mcp --transport streamable-http --port 8000
```

## Docker

```bash
docker build -t kaos-mcp-rawpython .
docker run -e MCP_TOOLS_STRING='def echo(x: str) -> str: return x' -p 8000:8000 kaos-mcp-rawpython
```
