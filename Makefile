.PHONY: help build docker-build docker-build-operator docker-build-runtime docker-build-mcp-servers test deploy clean kind-e2e kind-create kind-delete kind-clean generate-kind-values

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
	@./hack/install-metallb.sh

kind-delete:
	@./hack/kind-delete.sh

kind-e2e: kind-create
	@./hack/run-e2e-tests.sh

# Generate KIND E2E values file (not checked in - generated at build time)
generate-kind-values:
	@./hack/update-kind-e2e-values.sh

# Clean generated KIND E2E values file
kind-clean:
	@rm -f hack/kind-e2e-values.yaml
	@echo "Cleaned hack/kind-e2e-values.yaml"
