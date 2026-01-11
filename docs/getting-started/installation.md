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
git clone https://github.com/your-org/agentic-kubernetes-operator.git
cd agentic-kubernetes-operator/operator

# Install with default values
helm install agentic-operator chart/ -n agentic-system --create-namespace

# Or customize installation
helm install agentic-operator chart/ -n agentic-system --create-namespace \
  --set controllerManager.manager.image.repository=your-registry/agentic-operator \
  --set controllerManager.manager.image.tag=v1.0.0 \
  --set controllerManager.replicas=2
```

#### Helm Values

Key configurable values in `chart/values.yaml`:

| Value | Description | Default |
|-------|-------------|---------|
| `controllerManager.manager.image.repository` | Operator image repository | `agentic-operator` |
| `controllerManager.manager.image.tag` | Operator image tag | `latest` |
| `controllerManager.replicas` | Number of operator replicas | `1` |
| `controllerManager.manager.resources` | Resource limits/requests | See values.yaml |
| `defaultImages.agentRuntime` | Default agent container image | `agentic-agent:latest` |
| `defaultImages.mcpServer` | Default MCP server image | `agentic-agent:latest` |
| `defaultImages.litellm` | Default LiteLLM proxy image | `ghcr.io/berriai/litellm:main-latest` |
| `defaultImages.ollama` | Default Ollama image | `alpine/ollama:latest` |
| `gateway.defaultTimeouts.agent` | Default timeout for Agent HTTPRoutes | `120s` |
| `gateway.defaultTimeouts.modelAPI` | Default timeout for ModelAPI HTTPRoutes | `120s` |
| `gateway.defaultTimeouts.mcp` | Default timeout for MCPServer HTTPRoutes | `30s` |
| `gatewayAPI.enabled` | Enable Gateway API integration | `false` |
| `gatewayAPI.createGateway` | Create a Gateway resource | `false` |
| `gatewayAPI.gatewayName` | Name of the Gateway resource | `agentic-gateway` |
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
git clone https://github.com/your-org/agentic-kubernetes-operator.git
cd agentic-kubernetes-operator/operator

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
kubectl get pods -n agentic-system
# Expected: agentic-operator-controller-manager-xxx Running

# Check CRDs are installed
kubectl get crds | grep ethical.institute
# Expected:
# agents.ethical.institute
# mcpservers.ethical.institute
# modelapis.ethical.institute
```

## Agent Container Image

The agent container image must be available in your cluster:

### Build Locally

```bash
cd python
docker build -t agentic-agent:latest .
```

### For Docker Desktop Kubernetes

Images built locally are automatically available.

### For Remote Clusters

Push to your container registry:

```bash
docker tag agentic-agent:latest your-registry/agentic-agent:latest
docker push your-registry/agentic-agent:latest
```

Then update agent deployments to use your registry.

## Ollama Setup

### Local Development (Proxy Mode)

Run Ollama on your host machine:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama
ollama serve

# Pull a model
ollama pull smollm2:135m
```

Use ModelAPI with Proxy mode to connect:

```yaml
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: ollama-proxy
spec:
  mode: Proxy
  proxyConfig:
    apiBase: "http://host.docker.internal:11434"  # Docker Desktop
    # apiBase: "http://host.minikube.internal:11434"  # Minikube
```

### In-Cluster (Hosted Mode)

Use ModelAPI with Hosted mode to run Ollama in the cluster:

```yaml
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: ollama-hosted
spec:
  mode: Hosted
  serverConfig:
    model: "smollm2:135m"
```

Note: Hosted mode pulls the model on first start, which can take several minutes.

## Uninstallation

### Helm Installation

```bash
# Remove all custom resources first
kubectl delete agents,mcpservers,modelapis --all-namespaces --all

# Uninstall Helm release
helm uninstall agentic-operator -n agentic-system

# Delete namespace (optional)
kubectl delete namespace agentic-system
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
kubectl logs -n agentic-system deployment/agentic-operator-controller-manager
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
