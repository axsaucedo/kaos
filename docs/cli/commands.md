# CLI Command Reference

Complete reference for all KAOS CLI commands.

## kaos install

Install the KAOS operator to your Kubernetes cluster using Helm.

```bash
kaos install [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--namespace` | `-n` | `kaos-system` | Kubernetes namespace to install into |
| `--release-name` | | `kaos` | Helm release name |
| `--version` | | latest | Specific chart version to install |
| `--set` | | | Set Helm values (can be repeated) |
| `--wait` | | false | Wait for pods to be ready |

### Examples

**Basic installation:**
```bash
kaos install
```

**Install to custom namespace:**
```bash
kaos install -n my-agents
```

**Install with custom values:**
```bash
kaos install --set gateway.enabled=true --set controllerManager.replicas=2
```

**Install specific version and wait:**
```bash
kaos install --version 0.1.0 --wait
```

---

## kaos uninstall

Remove the KAOS operator from your Kubernetes cluster.

```bash
kaos uninstall [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--namespace` | `-n` | `kaos-system` | Namespace to uninstall from |
| `--release-name` | | `kaos` | Helm release name |

### Examples

```bash
kaos uninstall
kaos uninstall -n my-agents
```

---

## kaos ui

Start a CORS-enabled proxy to the Kubernetes API and open the KAOS web UI.

```bash
kaos ui [OPTIONS]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--k8s-url` | auto | Kubernetes API server URL. Uses kubeconfig if not specified |
| `--expose-port` | `8080` | Port for the local CORS proxy |
| `--no-browser` | false | Don't automatically open the browser |

### How it Works

The `kaos ui` command:

1. Reads your kubeconfig to find the Kubernetes API server
2. Starts a local CORS-enabled reverse proxy on the specified port
3. Opens the KAOS UI in your default browser
4. The UI connects to your cluster through the local proxy

### Examples

**Start with defaults:**
```bash
kaos ui
```

**Use custom port:**
```bash
kaos ui --expose-port 9090
```

**Connect to specific cluster:**
```bash
kaos ui --k8s-url https://my-cluster.example.com:6443
```

**Start without opening browser:**
```bash
kaos ui --no-browser
```

---

## kaos version

Display the KAOS CLI version.

```bash
kaos version
```

### Output

```
kaos-cli 0.1.0
```

---

## Environment Variables

The CLI respects standard Kubernetes environment variables:

| Variable | Description |
|----------|-------------|
| `KUBECONFIG` | Path to kubeconfig file |
| `KUBERNETES_SERVICE_HOST` | In-cluster API host |
| `KUBERNETES_SERVICE_PORT` | In-cluster API port |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (see error message) |

## Troubleshooting

### Helm not found

```
Error: helm is not installed. Please install helm first.
```

Install Helm from https://helm.sh/docs/intro/install/

### Cannot connect to cluster

Ensure kubectl is configured correctly:
```bash
kubectl cluster-info
```

### Port already in use

Use a different port for the UI proxy:
```bash
kaos ui --expose-port 9090
```
