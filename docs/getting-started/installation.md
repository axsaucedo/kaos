# Installation

## Prerequisites

### Required
- Kubernetes cluster v1.24+
- kubectl configured with cluster access
- Docker (for building images)

### Optional
- Helm v3.6+ (for Helm installation)
- Ollama (for local LLM development)
- Go 1.21+ (for operator development)
- Python 3.12+ (for agent framework development)

## Operator Installation

### Option 1: Helm (Recommended)

Helm provides the most flexible installation with configurable values:

```bash
# Clone repository
git clone https://github.com/your-org/kaos.git
cd kaos/operator

# Install with default values
helm install kaos-operator chart/ -n kaos-system --create-namespace

# Or customize installation
helm install kaos-operator chart/ -n kaos-system --create-namespace \
  --set controllerManager.manager.image.repository=your-registry/kaos-operator \
  --set controllerManager.manager.image.tag=v1.0.0 \
  --set controllerManager.replicas=2
```

#### Helm Values

Key configurable values in `chart/values.yaml`:

| Value | Description | Default |
|-------|-------------|---------|
| `controllerManager.manager.image.repository` | Operator image repository | `axsauze/kaos-operator` |
| `controllerManager.manager.image.tag` | Operator image tag | `latest` |
| `controllerManager.replicas` | Number of operator replicas | `1` |
| `controllerManager.manager.resources` | Resource limits/requests | See values.yaml |
| `defaultImages.agentRuntime` | Default agent container image | `axsauze/kaos-agent:latest` |
| `defaultImages.mcpServer` | Default MCP server image | `axsauze/kaos-agent:latest` |
| `defaultImages.litellm` | Default LiteLLM proxy image | `ghcr.io/berriai/litellm:main-latest` |
| `defaultImages.ollama` | Default Ollama image | `alpine/ollama:latest` |
| `gateway.defaultTimeouts.agent` | Default timeout for Agent HTTPRoutes | `120s` |
| `gateway.defaultTimeouts.modelAPI` | Default timeout for ModelAPI HTTPRoutes | `120s` |
| `gateway.defaultTimeouts.mcp` | Default timeout for MCPServer HTTPRoutes | `30s` |
| `gatewayAPI.enabled` | Enable Gateway API integration | `false` |
| `gatewayAPI.createGateway` | Create a Gateway resource | `false` |
| `gatewayAPI.gatewayName` | Name of the Gateway resource | `kaos-gateway` |
| `gatewayAPI.gatewayClassName` | GatewayClass to use (required if createGateway) | `""` |

#### Generate Helm Chart

To regenerate the Helm chart from kustomize manifests:

```bash
cd operator
make helm
```

### Option 2: Deploy from Repository (Kustomize)

```bash
# Clone repository
git clone https://github.com/your-org/kaos.git
cd kaos/operator

# Deploy CRDs and operator
make deploy
```

### Option 3: Deploy CRDs Only (Local Development)

For development, you can run the operator locally:

```bash
# Install CRDs only
cd operator
make install

# Run operator locally
make run
```

### Option 4: Manual Installation

```bash
# Apply CRDs
kubectl apply -f operator/config/crd/bases/

# Apply RBAC
kubectl apply -f operator/config/rbac/

# Deploy operator
kubectl apply -f operator/config/manager/
```

## Verify Installation

```bash
# Check operator pod
kubectl get pods -n kaos-system
# Expected: kaos-operator-controller-manager-xxx Running

# Check CRDs are installed
kubectl get crds | grep kaos.tools
# Expected:
# agents.kaos.tools
# mcpservers.kaos.tools
# modelapis.kaos.tools
```

## Agent Container Image

The agent container image must be available in your cluster:

### Build Locally

```bash
cd python
docker build -t kaos-agent:latest .
```

### For Docker Desktop Kubernetes

Images built locally are automatically available.

### For Remote Clusters

Push to your container registry:

```bash
docker tag kaos-agent:latest your-registry/kaos-agent:latest
docker push your-registry/kaos-agent:latest
```

Then update agent deployments to use your registry.

## Ollama Setup

### In-Cluster (Hosted Mode) - Recommended

Use ModelAPI with Hosted mode to run Ollama in the cluster:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
spec:
  mode: Hosted
  hostedConfig:
    model: "smollm2:135m"
```

Note: Hosted mode pulls the model on first start, which can take several minutes.

### External Ollama (Proxy Mode)

For development with Ollama running outside the cluster, use Proxy mode:

```bash
# Install and run Ollama on your host
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
ollama pull smollm2:135m
```

```yaml
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ollama-proxy
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "http://your-ollama-host:11434"
```

## Uninstallation

### Helm Installation

```bash
# Remove all custom resources first
kubectl delete agents,mcpservers,modelapis --all-namespaces --all

# Uninstall Helm release
helm uninstall kaos-operator -n kaos-system

# Delete namespace (optional)
kubectl delete namespace kaos-system
```

### Kustomize Installation

```bash
# Remove all custom resources first
kubectl delete agents,mcpservers,modelapis --all-namespaces --all

# Remove operator
cd operator
make undeploy
```

## Troubleshooting

### Operator Not Starting

Check RBAC permissions:

```bash
kubectl logs -n kaos-system deployment/kaos-operator-controller-manager
```

Common issue: Missing leases permission for leader election.

### Agent Not Becoming Ready

Check if ModelAPI is ready first:

```bash
kubectl get modelapi -n <namespace>
```

Check agent pod logs:

```bash
kubectl logs -n <namespace> -l app=<agent-name>
```

### MCP Server CrashLoopBackOff

Check if the MCP package is valid:

```bash
kubectl logs -n <namespace> -l app=<mcpserver-name>
```

For `toolsString`, verify Python syntax is correct.
