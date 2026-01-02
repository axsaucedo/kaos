.PHONY: help build docker-build deploy generate manifests test clean envtest

# Configuration
IMG ?= agentic-operator:latest
CONTROLLER_GEN ?= $(shell which controller-gen || echo "$(shell pwd)/bin/controller-gen")
CRD_OPTIONS ?= "crd:generateEmbeddedObjectMeta=true"
SETUP_ENVTEST ?= $(shell which setup-envtest)

help:
	@echo "Operator build targets:"
	@echo "  build           - Build operator binary"
	@echo "  docker-build    - Build operator Docker image"
	@echo "  deploy          - Deploy operator to K8s cluster"
	@echo "  generate        - Generate CRD code"
	@echo "  manifests       - Generate CRD manifests"
	@echo "  test            - Run controller tests"
	@echo "  clean           - Clean build artifacts"

# Build operator binary
build: generate manifests
	go build -o bin/manager main.go

# Build Docker image
docker-build: build
	docker build -t ${IMG} .

# Deploy to K8s cluster (uses kustomize via -k flag)
deploy: manifests
	kubectl apply -k config/crd/
	kubectl apply -k config/rbac/
	kubectl apply -k config/manager/

# Generate CRD code
generate:
	$(CONTROLLER_GEN) object paths="./..."

# Generate CRD manifests
manifests:
	$(CONTROLLER_GEN) $(CRD_OPTIONS) rbac:roleName=agentic-operator paths="./..." output:crd:artifacts:config=config/crd/bases

# Install envtest binary (one-time setup)
envtest:
	@test -n "$(SETUP_ENVTEST)" || { echo "Installing setup-envtest..."; go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest; }
	$(SETUP_ENVTEST) use 1.28 --bin-dir $(shell pwd)/bin

# Run tests
test: generate manifests envtest
	KUBEBUILDER_ASSETS="$(shell $(SETUP_ENVTEST) use 1.28 --bin-dir $(shell pwd)/bin -p path)" go test ./... -coverprofile cover.out -v

# Clean artifacts
clean:
	rm -rf bin/ cover.out
	go clean -testcache
