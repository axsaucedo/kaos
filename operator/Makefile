.PHONY: help build docker-build deploy generate manifests test test-unit clean envtest helm kind-create kind-delete kind-load-images kind-e2e-install-kaos kind-e2e-run-tests e2e-test e2e-test-seq e2e-clean

# Configuration
IMG ?= axsauze/kaos-operator:latest
CONTROLLER_GEN ?= $(shell which controller-gen || echo "$(shell pwd)/bin/controller-gen")
CRD_OPTIONS ?= "crd:generateEmbeddedObjectMeta=true"
SETUP_ENVTEST ?= $(shell which setup-envtest)
HELMIFY ?= $(shell which helmify || echo "$(HOME)/go/bin/helmify")

# KIND cluster configuration
KIND_CLUSTER_NAME ?= kaos-e2e

help:
	@echo "Operator build targets:"
	@echo "  build           - Build operator binary"
	@echo "  docker-build    - Build operator Docker image"
	@echo "  deploy          - Deploy operator to K8s cluster"
	@echo "  generate        - Generate CRD code"
	@echo "  manifests       - Generate CRD manifests"
	@echo "  helm            - Generate Helm chart from kustomize"
	@echo "  test-unit       - Run Go unit/integration tests (envtest)"
	@echo "  clean           - Clean build artifacts"
	@echo ""
	@echo "KIND E2E targets:"
	@echo "  kind-create           - Create KIND cluster with registry, Gateway, MetalLB"
	@echo "  kind-delete           - Delete KIND cluster"
	@echo "  kind-load-images      - Build and load images into KIND"
	@echo "  kind-e2e-install-kaos - Generate values and install KAOS operator"
	@echo "  kind-e2e-run-tests    - Run E2E tests (depends on load-images + install-kaos)"
	@echo "  e2e-test              - Run E2E tests (parallel, requires operator)"
	@echo "  e2e-test-seq          - Run E2E tests sequentially"
	@echo "  e2e-clean             - Clean up E2E test resources"

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

undeploy: manifests
	kubectl delete agents,mcpservers,modelapis --all-namespaces --all
	kubectl delete -k config/crd/
	kubectl delete -k config/rbac/
	kubectl delete -k config/manager/

# Generate CRD code
generate:
	$(CONTROLLER_GEN) object paths="./..."

# Generate CRD manifests
manifests:
	$(CONTROLLER_GEN) $(CRD_OPTIONS) rbac:roleName=kaos-operator paths="./..." output:crd:artifacts:config=config/crd/bases

# Install envtest binary (one-time setup)
envtest:
	@test -n "$(SETUP_ENVTEST)" || { echo "Installing setup-envtest..."; go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest; }
	$(SETUP_ENVTEST) use 1.28 --bin-dir $(shell pwd)/bin

# Run Go unit/integration tests
test-unit: generate manifests envtest
	KUBEBUILDER_ASSETS="$(shell $(SETUP_ENVTEST) use 1.28 --bin-dir $(shell pwd)/bin -p path)" go test ./... -coverprofile cover.out -v

# Alias for backward compatibility
test: test-unit

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

# === KIND E2E Test Targets ===

# Configuration for KIND E2E
REGISTRY ?= kind-local
OPERATOR_TAG ?= dev
AGENT_TAG ?= dev
LITELLM_VERSION ?= v1.56.5
OLLAMA_TAG ?= latest
HELM_VALUES_FILE ?= $(shell pwd)/hack/kind-e2e-values.yaml

# Create KIND cluster with registry, Gateway, MetalLB
kind-create:
	@./hack/kind-with-registry.sh
	@./hack/install-gateway.sh
	@./hack/install-metallb.sh

# Delete KIND cluster
kind-delete:
	@./hack/kind-delete.sh

# Build images and load into KIND cluster
kind-load-images:
	@REGISTRY=$(REGISTRY) KIND_CLUSTER_NAME=$(KIND_CLUSTER_NAME) \
		OPERATOR_TAG=$(OPERATOR_TAG) AGENT_TAG=$(AGENT_TAG) \
		LITELLM_VERSION=$(LITELLM_VERSION) OLLAMA_TAG=$(OLLAMA_TAG) \
		./hack/build-push-images.sh

# Generate Helm values and install KAOS operator in KIND
kind-e2e-install-kaos:
	@echo "=== Generating Helm values ==="
	@REGISTRY=$(REGISTRY) OPERATOR_TAG=$(OPERATOR_TAG) AGENT_TAG=$(AGENT_TAG) \
		LITELLM_VERSION=$(LITELLM_VERSION) OLLAMA_TAG=$(OLLAMA_TAG) \
		./hack/update-kind-e2e-values.sh
	@echo "=== Installing KAOS operator ==="
	@kubectl create namespace kaos-system 2>/dev/null || true
	@helm upgrade --install kaos chart/ \
		--namespace kaos-system \
		-f $(HELM_VALUES_FILE) \
		--set gatewayAPI.enabled=true \
		--set gatewayAPI.createGateway=true \
		--set gatewayAPI.gatewayClassName=envoy-gateway \
		--wait --timeout 120s
	@echo "=== KAOS operator installed ==="

# Run E2E tests in KIND (requires kind-load-images and kind-e2e-install-kaos)
kind-e2e-run-tests: kind-load-images kind-e2e-install-kaos
	@./hack/run-e2e-tests.sh

# Run E2E tests (parallel) - requires existing cluster with operator installed
# Cap at 4 workers to avoid "out of pty devices" errors on high-CPU machines
e2e-test:
	@cd tests && \
	CPUS="$$(nproc --all 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"; \
	JOBS="$$(( CPUS > 4 ? 4 : CPUS ))"; \
	uv run pytest e2e/ -v -n "$$JOBS" --dist loadscope

# Run E2E tests sequentially - requires existing cluster with operator installed
e2e-test-seq:
	@cd tests && uv run pytest e2e/ -v -s --log-cli-level=DEBUG

# Clean up E2E test resources
e2e-clean:
	@echo "Cleaning up E2E test resources..."
	-helm uninstall kaos -n kaos-system 2>/dev/null || true
	-kubectl delete namespace kaos-system --wait=false 2>/dev/null || true
	-kubectl get ns -o name | grep e2e | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
	@sleep 3
