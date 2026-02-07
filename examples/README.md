# KAOS Examples

Executable Jupyter notebooks demonstrating KAOS features.

## Available Examples

| Example | Description |
|---------|-------------|
| [custom-mcp-server.ipynb](custom-mcp-server.ipynb) | Build and deploy a custom MCP server with FastMCP |
| [kaos-monkey.ipynb](kaos-monkey.ipynb) | Chaos engineering agent with Kubernetes tools |
| [multi-agent-telemetry.ipynb](multi-agent-telemetry.ipynb) | Multi-agent delegation with coordinator pattern |
| [unified-mcp-gateway.ipynb](unified-mcp-gateway.ipynb) | Optimized MCPs with pctx Unified Code Mode |

## Prerequisites

- KAOS operator installed in your cluster
- `kaos-cli` installed (`pip install kaos-cli`)
- `kubectl` configured to your cluster
- Jupyter installed (`pip install jupyter jupytext`)

## Running Examples

```bash
# Start Jupyter
jupyter notebook

# Or run headlessly with Jupytext
jupytext --execute kaos-monkey.ipynb
```

## Documentation

These notebooks are generated from the [documentation examples](/docs/examples/). The markdown files are the source of truth and are tested in CI.
