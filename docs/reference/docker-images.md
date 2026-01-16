# Docker Images

Official Docker images for KAOS are published to Docker Hub.

## Available Images

| Image | Description | Source |
|-------|-------------|--------|
| `axsauze/kaos-operator:latest` | Kubernetes operator controller | `operator/Dockerfile` |
| `axsauze/kaos-agent:latest` | Agent runtime and MCP server | `python/Dockerfile` |

## Pulling Images

```bash
docker pull axsauze/kaos-operator:latest
docker pull axsauze/kaos-agent:latest
```

## Image Tags

- `latest` - Built from main branch on each merge
- `<sha>` - Git commit SHA for specific versions

## Helm Chart Defaults

The Helm chart uses these default images:

```yaml
# operator/chart/values.yaml
controllerManager:
  manager:
    image:
      repository: axsauze/kaos-operator
      tag: latest

defaultImages:
  agentRuntime: "axsauze/kaos-agent:latest"
  mcpServer: "axsauze/kaos-agent:latest"
  litellm: "ghcr.io/berriai/litellm:main-latest"
  ollama: "alpine/ollama:latest"
```

## Overriding Images

### At Install Time

```bash
helm install kaos-operator ./operator/chart \
  --namespace kaos-system --create-namespace \
  --set controllerManager.manager.image.tag=v1.0.0 \
  --set defaultImages.agentRuntime=myregistry/kaos-agent:v1.0.0
```

### In CRD (Agent)

Agent images can be customized via podSpec:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: my-agent
spec:
  modelAPI: ollama
  podSpec:
    containers:
    - name: agent
      image: myregistry/custom-agent:v1.0.0
```

## Building Images Locally

```bash
# Build operator
cd operator
docker build -t kaos-operator:dev .

# Build agent
cd python
docker build -t kaos-agent:dev .
```

## CI/CD Pipeline

Images are automatically built and pushed via GitHub Actions:

- **Trigger**: Push to `main` branch
- **Workflow**: `.github/workflows/docker-push.yaml`
- **Tags**: `latest` and git commit SHA

### Required Secrets

For the GitHub Action to push images:
- `DOCKERHUB_USERNAME` - Docker Hub username
- `DOCKERHUB_TOKEN` - Docker Hub access token

## Third-Party Images

KAOS uses these third-party images:

| Image | Used By | Purpose |
|-------|---------|---------|
| `ghcr.io/berriai/litellm:main-latest` | ModelAPI (Proxy mode) | LLM API proxy |
| `alpine/ollama:latest` | ModelAPI (Hosted mode) | In-cluster Ollama |

These can be overridden in the Helm chart values.
