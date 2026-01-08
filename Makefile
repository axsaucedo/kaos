.PHONY: help build docker-build docker-build-operator docker-build-runtime docker-build-mcp-servers test deploy clean kind-e2e kind-create kind-delete

# KIND cluster configuration
KIND_CLUSTER_NAME ?= agentic-e2e
REGISTRY_NAME ?= kind-registry
REGISTRY_PORT ?= 5001
LOCAL_REGISTRY ?= localhost:$(REGISTRY_PORT)
KIND_REGISTRY ?= $(REGISTRY_NAME):$(REGISTRY_PORT)

# Default target
help:
	@echo "Agentic Kubernetes Operator - Build Orchestration"
	@echo ""
	@echo "Available targets:"
	@echo "  build                    - Build all components"
	@echo "  docker-build             - Build all Docker images"
	@echo "  docker-build-operator    - Build operator Docker image"
	@echo "  docker-build-runtime     - Build runtime Docker image"
	@echo "  docker-build-mcp-servers - Build MCP servers Docker image"
	@echo "  test                     - Run all tests"
	@echo "  deploy                   - Deploy operator to K8s cluster"
	@echo "  clean                    - Clean all build artifacts"
	@echo "  kind-create              - Create KIND cluster with registry"
	@echo "  kind-delete              - Delete KIND cluster"
	@echo "  kind-e2e                 - Run E2E tests in KIND cluster"
	@echo "  help                     - Show this help message"

# Build all components
build:
	@echo "Building all components..."
	cd operator && make build
	cd runtime/server && make build

# Docker builds
docker-build: docker-build-operator docker-build-runtime
	@echo "All Docker images built successfully"

docker-build-operator:
	@echo "Building operator Docker image..."
	cd operator && make docker-build

docker-build-runtime:
	@echo "Building runtime Docker image..."
	cd runtime/server && make docker-build

# Test all components
test:
	@echo "Running all tests..."
	cd operator && make test
	cd runtime/server && make test
	python -m pytest tests/ -v

# Deploy operator to K8s
deploy:
	@echo "Deploying operator to Kubernetes..."
	cd operator && make deploy

# Clean all build artifacts
clean:
	@echo "Cleaning all build artifacts..."
	cd operator && make clean
	cd runtime/server && make clean
	rm -rf build/ dist/ *.egg-info/

# Development setup
setup-dev:
	@echo "Setting up local development environment..."
	./scripts/setup-local-dev.sh

# KIND cluster management
kind-create:
	@./hack/kind-with-registry.sh
	@./hack/install-gateway.sh

kind-delete:
	@echo "Deleting KIND cluster..."
	-kind delete cluster --name $(KIND_CLUSTER_NAME)
	-docker rm -f $(REGISTRY_NAME)

kind-e2e: kind-create
	@echo "Building and pushing images to KIND registry..."
	cd operator && docker build -t $(LOCAL_REGISTRY)/agentic-operator:latest . && docker push $(LOCAL_REGISTRY)/agentic-operator:latest
	cd python && docker build -t $(LOCAL_REGISTRY)/agentic-agent:latest . && docker push $(LOCAL_REGISTRY)/agentic-agent:latest
	cd python && docker build -t $(LOCAL_REGISTRY)/agentic-mcp-server:latest . && docker push $(LOCAL_REGISTRY)/agentic-mcp-server:latest
	@echo "Creating Helm values for KIND registry..."
	@echo "controllerManager:" > /tmp/kind-e2e-values.yaml
	@echo "  manager:" >> /tmp/kind-e2e-values.yaml
	@echo "    image:" >> /tmp/kind-e2e-values.yaml
	@echo "      repository: $(LOCAL_REGISTRY)/agentic-operator" >> /tmp/kind-e2e-values.yaml
	@echo "      tag: latest" >> /tmp/kind-e2e-values.yaml
	@echo "    imagePullPolicy: Always" >> /tmp/kind-e2e-values.yaml
	@echo "defaultImages:" >> /tmp/kind-e2e-values.yaml
	@echo "  agentRuntime: $(LOCAL_REGISTRY)/agentic-agent:latest" >> /tmp/kind-e2e-values.yaml
	@echo "  mcpServer: $(LOCAL_REGISTRY)/agentic-mcp-server:latest" >> /tmp/kind-e2e-values.yaml
	@echo "Running E2E tests..."
	cd operator/tests && HELM_VALUES_FILE=/tmp/kind-e2e-values.yaml make test
