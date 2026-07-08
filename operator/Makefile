.PHONY: help build docker-build deploy generate manifests test test-unit clean envtest helm kind-create kind-delete kind-load-images kind-e2e-install-kaos kind-e2e-run-tests e2e-test e2e-test-seq e2e-clean kind-load-aib-images kind-e2e-install-aib e2e-test-aib kind-e2e-aib

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
	@echo "  kind-load-images      - Build and load images into KIND (matches chart defaults)"
	@echo "  kind-e2e-install-kaos - Install KAOS operator with Gateway API enabled"
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
	@test -n "$(SETUP_ENVTEST)" || { echo "Installing setup-envtest..."; go install sigs.k8s.io/controller-runtime/tools/setup-envtest@release-0.24; }
	$(SETUP_ENVTEST) use 1.28 --bin-dir $(shell pwd)/bin

# Run Go unit/integration tests
test-unit: generate manifests envtest
	KUBEBUILDER_ASSETS="$(shell $(SETUP_ENVTEST) use 1.28 --bin-dir $(shell pwd)/bin -p path)" go test ./... -coverprofile cover.out -v

# Alias for backward compatibility
test: test-unit

# Generate Helm chart from kustomize manifests
# CRDs are moved to crds/ dir so --skip-crds works properly during install
helm: manifests
	@test -x $(HELMIFY) || { echo "Installing helmify..."; go install github.com/arttor/helmify/cmd/helmify@v0.4.18; }
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

# Configuration for KIND E2E - matches chart/values.yaml defaults
REGISTRY ?= axsauze
VERSION := $(shell cat $(shell pwd)/../VERSION 2>/dev/null || echo "dev")
OPERATOR_TAG ?= $(VERSION)
AGENT_TAG ?= $(VERSION)
LITELLM_IMAGE ?= ghcr.io/berriai/litellm:main-stable
OLLAMA_IMAGE ?= ollama/ollama:latest

# Create KIND cluster with registry
kind-create:
	@./hack/kind-with-registry.sh

# Delete KIND cluster
kind-delete:
	@./hack/kind-delete.sh

# Build images and load into KIND cluster
kind-load-images:
	@REGISTRY=$(REGISTRY) KIND_CLUSTER_NAME=$(KIND_CLUSTER_NAME) \
		OPERATOR_TAG=$(OPERATOR_TAG) AGENT_TAG=$(AGENT_TAG) \
		LITELLM_IMAGE=$(LITELLM_IMAGE) OLLAMA_IMAGE=$(OLLAMA_IMAGE) \
		./hack/build-push-images.sh

# Image tag configuration (defaults to chart values, override for CI)
IMAGE_TAG ?= $(shell cat ../VERSION 2>/dev/null || echo "v0.1.4-dev")
REGISTRY ?= axsauze

# Install KAOS operator in KIND using kaos CLI
kind-e2e-install-kaos:
	@echo "=== Installing KAOS operator via kaos CLI ==="
	@pip install -e ../kaos-cli -q 2>/dev/null || true
	@kaos system install \
		--gateway-enabled \
		--metallb-enabled \
		--chart-path chart/ \
		--set controllerManager.manager.image.repository=$(REGISTRY)/kaos-operator \
		--set controllerManager.manager.image.tag=$(IMAGE_TAG) \
		--set defaultImages.agentRuntime=$(REGISTRY)/kaos-agent:$(IMAGE_TAG) \
		--set defaultImages.mcpServer=$(REGISTRY)/kaos-mcp-server:$(IMAGE_TAG) \
		--set defaultImages.mcpPythonString=$(REGISTRY)/kaos-mcp-python-string:$(IMAGE_TAG) \
		--set defaultImages.mcpPctxCodemode=$(REGISTRY)/kaos-mcp-pctx-codemode:$(IMAGE_TAG) \
		--set defaultImages.mcpFastmcpCodemode=$(REGISTRY)/kaos-mcp-fastmcp-codemode:$(IMAGE_TAG) \
		--set defaultImages.memoryService=$(REGISTRY)/kaos-memory-service:$(IMAGE_TAG) \
		--wait
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
	-kaos system uninstall --gateway-enabled --metallb-enabled 2>/dev/null || helm uninstall kaos -n kaos-system 2>/dev/null || true
	-kubectl delete namespace kaos-system --wait=false 2>/dev/null || true
	-kubectl get ns -o name | grep e2e | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
	@sleep 3

# --- Agent-auth E2E (identity broker + Go sync service) ----------------------
# Opt-in, local-only suite that stands up the identity broker and the sync
# service alongside the operator and verifies per-agent credential Secrets are
# minted and mounted into agent pods. Requires the (gitignored) identity-broker
# clone checked out next to this repository and its images built locally.
AIB_CHART_PATH ?= $(PWD)/../agentic-identity-broker/charts/agentic-identity-broker
AIB_VALUES_PATH ?= $(AIB_CHART_PATH)/values-dev.yaml
AIB_IMAGE ?= agentic-identity-broker:0.1.0
SYNC_IMAGE ?= axsauze/kaos-sync:dev
AIB_OPERATOR_TAG ?= aib-e2e
AIB_AGENT_IMAGE ?= axsauze/kaos-agent:0.4.8-dev

# Load the operator, agent, sync, broker, and LiteLLM images into KIND.
kind-load-aib-images:
	@kind load docker-image \
		$(REGISTRY)/kaos-operator:$(AIB_OPERATOR_TAG) \
		$(AIB_AGENT_IMAGE) \
		$(SYNC_IMAGE) \
		$(AIB_IMAGE) \
		$(LITELLM_IMAGE) \
		--name $(KIND_CLUSTER_NAME)

# Install KAOS with agent auth, the identity broker, and the Go sync service.
kind-e2e-install-aib:
	@pip install -e ../kaos-cli -q 2>/dev/null || true
	@kaos system install \
		--namespace kaos-system \
		--auth-enabled --no-user-auth --no-token-exchange \
		--gateway-enabled --metallb-enabled \
		--chart-path chart/ \
		--set controllerManager.manager.image.repository=$(REGISTRY)/kaos-operator \
		--set controllerManager.manager.image.tag=$(AIB_OPERATOR_TAG) \
		--set defaultImages.agentRuntime=$(AIB_AGENT_IMAGE) \
		--aib-chart-path $(AIB_CHART_PATH) \
		--aib-values $(AIB_VALUES_PATH) \
		--sync-chart-path ../sync-service/chart \
		--sync-image-repository $(REGISTRY)/kaos-sync \
		--sync-image-tag $(word 2,$(subst :, ,$(SYNC_IMAGE))) \
		--wait

# Run only the agent-auth credential test against an installed cluster.
e2e-test-aib:
	@cd tests && KAOS_AIB_E2E=1 uv run pytest e2e/test_aib_sync_e2e.py -v -s

# Full local agent-auth E2E: load images, install, run the test.
kind-e2e-aib: kind-load-aib-images kind-e2e-install-aib e2e-test-aib
