# KAOS CLI

Command-line interface for KAOS (K8s Agent Orchestration System).

## Installation

```bash
cd kaos-cli
uv sync
source .venv/bin/activate
```

## Usage

### Start UI Proxy

Start a CORS-enabled proxy to the Kubernetes API server:

```bash
kaos ui
```

This starts a local proxy on port 8080 that:
- Proxies requests to the Kubernetes API using your kubeconfig credentials
- Adds CORS headers to enable browser-based access
- Exposes the `mcp-session-id` header for MCP protocol support

Options:
- `--k8s-url`: Override the Kubernetes API URL (default: from kubeconfig)
- `--expose-port`: Port to expose the proxy on (default: 8080)

Example:
```bash
# Use default settings
kaos ui

# Custom port
kaos ui --expose-port 9000

# Custom K8s URL
kaos ui --k8s-url https://my-cluster:6443
```

### Version

```bash
kaos version
```

## Development

```bash
# Run tests
pytest

# Run directly
python -m kaos_cli.main ui
```
