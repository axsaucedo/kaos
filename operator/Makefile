.PHONY: help build docker-build deploy generate manifests test clean envtest helm

# Configuration
IMG ?= agentic-operator:latest
CONTROLLER_GEN ?= $(shell which controller-gen || echo "$(shell pwd)/bin/controller-gen")
CRD_OPTIONS ?= "crd:generateEmbeddedObjectMeta=true"
SETUP_ENVTEST ?= $(shell which setup-envtest)
HELMIFY ?= $(shell which helmify || echo "$(HOME)/go/bin/helmify")

help:
	@echo "Operator build targets:"
	@echo "  build           - Build operator binary"
	@echo "  docker-build    - Build operator Docker image"
	@echo "  deploy          - Deploy operator to K8s cluster"
	@echo "  generate        - Generate CRD code"
	@echo "  manifests       - Generate CRD manifests"
	@echo "  helm            - Generate Helm chart from kustomize"
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

# Generate Helm chart from kustomize manifests
# CRDs are moved to crds/ dir so --skip-crds works properly during install
helm: manifests
	@test -x $(HELMIFY) || { echo "Installing helmify..."; go install github.com/arttor/helmify/cmd/helmify@latest; }
	kustomize build config/ | $(HELMIFY) chart
	@mkdir -p chart/crds
	@mv chart/templates/*-crd.yaml chart/crds/ 2>/dev/null || true
	@for f in chart/crds/*.yaml; do sed -i '' '/{{.*}}/d' "$$f" 2>/dev/null; sed -i '' '/^  labels:$$/d' "$$f" 2>/dev/null; done || true
	@echo "Helm chart generated in chart/"

# Clean artifacts
clean:
	rm -rf bin/ cover.out
	go clean -testcache
