# KAOS UI Overview

The KAOS UI is a web-based dashboard for managing and monitoring your AI agents running on Kubernetes. It provides a visual interface for viewing agents, MCP servers, model APIs, and debugging agent interactions.

![KAOS Dashboard Home](/ui-overview/dashboard-home.png)

## Features

- **Agent Management** - View, create, and monitor agents
- **Real-time Chat** - Test agents directly from the UI
- **Memory Inspector** - Debug agent memory and conversation history
- **MCP Tool Debugging** - Test MCP server tools interactively
- **Model API Testing** - Verify model connectivity
- **Pod Management** - View logs and status of running pods
- **YAML Editor** - Edit resource configurations directly

## Getting Started

### Start the UI

Use the KAOS CLI to start the UI:

```bash
kaos ui
```

This will:
1. Start a local CORS proxy to your Kubernetes cluster
2. Open the KAOS UI in your default browser

### Configure Connection

On first launch, configure the connection to your cluster:

1. Navigate to **Settings > Connectivity**
2. Enter your proxy URL (default: `http://localhost:8080`)
3. Select the namespace containing your agents
4. Click **Save**

![Settings Connectivity](/ui-overview/dashboard-settings-connectivity.png)

## Architecture

The KAOS UI is a static web application hosted on GitHub Pages. It connects to your Kubernetes cluster through a local CORS proxy started by the `kaos ui` command.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Browser   │────▶│  CORS Proxy  │────▶│  Kubernetes API │
│  (KAOS UI)  │     │  (localhost) │     │    (cluster)    │
└─────────────┘     └──────────────┘     └─────────────────┘
```

This architecture allows:
- No authentication tokens stored in the browser
- Works with any Kubernetes cluster
- Respects your existing kubeconfig and RBAC

## Next Steps

- [Features Guide](./features) - Detailed walkthrough of UI features
- [CLI Commands](/cli/commands) - CLI command reference
- [Quick Start](/getting-started/quickstart) - Deploy your first agent
