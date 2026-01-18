# KAOS CLI

The KAOS CLI (`kaos-cli`) is a command-line tool for managing KAOS (K8s Agent Orchestration System). It provides commands for installing the operator, launching the web UI, and managing your agent deployments.

## Installation

Install the CLI using pip:

```bash
pip install kaos-cli
```

Or using pipx for isolated installation:

```bash
pipx install kaos-cli
```

## Quick Start

### Install the Operator

Install the KAOS operator to your Kubernetes cluster:

```bash
kaos install
```

This installs the operator to the `kaos-system` namespace using Helm.

### Launch the UI

Start the web UI to manage your agents visually:

```bash
kaos ui
```

This starts a local CORS proxy and opens the KAOS UI in your browser.

### Check Version

```bash
kaos version
```

## Requirements

- **Python 3.12+** - For running the CLI
- **kubectl** - Configured with access to your Kubernetes cluster
- **Helm 3** - Required for the `install` command

## Next Steps

- [Command Reference](./commands) - Detailed documentation for all commands
- [UI Overview](/ui/overview) - Learn about the web interface
- [Quick Start](/getting-started/quickstart) - Deploy your first agent
