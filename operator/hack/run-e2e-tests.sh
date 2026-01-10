#!/bin/bash
# Runs E2E tests in KIND cluster.
# This script builds all images, loads them into KIND, and runs tests.
#
# The operator is installed once at the start and uninstalled at the end.
# Port-forward is maintained throughout the test run.
#
# Prerequisites:
#   - KIND cluster created with: make kind-create (from operator/)
#   - Gateway and MetalLB installed (done by kind-create)
set -o errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPERATOR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${OPERATOR_ROOT}/.." && pwd)"

# Configuration - single source of truth for versions
export KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-agentic-e2e}"
export REGISTRY="${REGISTRY:-kind-local}"
export OPERATOR_TAG="${OPERATOR_TAG:-dev}"
export AGENT_TAG="${AGENT_TAG:-dev}"
export LITELLM_VERSION="${LITELLM_VERSION:-v1.56.5}"
export OLLAMA_TAG="${OLLAMA_TAG:-latest}"

echo "=== Generating Helm values file ==="
"${SCRIPT_DIR}/update-kind-e2e-values.sh"
HELM_VALUES_FILE="${SCRIPT_DIR}/kind-e2e-values.yaml"

echo ""
echo "=== Building images and loading into KIND ==="
"${SCRIPT_DIR}/build-push-images.sh"

echo ""
echo "=== Setting up test environment ==="
cd "${OPERATOR_ROOT}/tests"

# Ensure virtual environment exists and has dependencies
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    uv venv
fi
source .venv/bin/activate
uv pip install -e .

echo "Using Helm values: ${HELM_VALUES_FILE}"

# Install operator with Gateway
echo "Installing operator with Gateway..."
kubectl create namespace agentic-e2e-system 2>/dev/null || true
kubectl apply --server-side -f "${OPERATOR_ROOT}/config/crd/bases"
helm upgrade --install agentic-e2e "${OPERATOR_ROOT}/chart" \
    --namespace agentic-e2e-system \
    -f "${HELM_VALUES_FILE}" \
    --set gatewayAPI.enabled=true \
    --set gatewayAPI.createGateway=true \
    --set gatewayAPI.gatewayClassName=envoy-gateway \
    --skip-crds \
    --wait --timeout 120s

# Wait for Gateway to be programmed
echo "Waiting for Gateway to be programmed..."
for i in {1..30}; do
    STATUS=$(kubectl get gateway agentic-gateway -n agentic-e2e-system -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}' 2>/dev/null || echo "")
    if [ "$STATUS" = "True" ]; then
        echo "Gateway is programmed!"
        break
    fi
    echo "Waiting for Gateway... (attempt $i/30)"
    sleep 2
done

# Get the Envoy Gateway service for port-forwarding
GATEWAY_SVC=$(kubectl get svc -n envoy-gateway-system -l "gateway.envoyproxy.io/owning-gateway-name=agentic-gateway" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -z "$GATEWAY_SVC" ]; then
    echo "ERROR: Could not find Gateway service"
    kubectl get svc -n envoy-gateway-system
    exit 1
fi
echo "Found Gateway service: ${GATEWAY_SVC}"

# Start port-forward in background
echo "Starting port-forward to Gateway..."
kubectl port-forward -n envoy-gateway-system "svc/${GATEWAY_SVC}" 8888:80 &
PORT_FORWARD_PID=$!
sleep 3

# Verify port-forward is working
if ! curl -s --connect-timeout 5 http://localhost:8888 > /dev/null 2>&1; then
    echo "Warning: Port-forward may not be ready, waiting longer..."
    sleep 5
fi

# Cleanup function - always uninstall operator and stop port-forward
cleanup() {
    echo ""
    echo "=== Cleaning up ==="
    echo "Stopping port-forward..."
    kill $PORT_FORWARD_PID 2>/dev/null || true
    
    echo "Uninstalling operator..."
    helm uninstall agentic-e2e -n agentic-e2e-system 2>/dev/null || true
    kubectl delete namespace agentic-e2e-system --wait=false 2>/dev/null || true
    
    # Clean up leftover test namespaces
    kubectl get ns -o name | grep -E "e2e-(gw[0-9]+|main)" | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
    
    # Clean up generated values file
    rm -f "${HELM_VALUES_FILE}"
}
trap cleanup EXIT

# Run tests
export HELM_VALUES_FILE="${HELM_VALUES_FILE}"
export GATEWAY_URL="http://localhost:8888"
# Tell conftest.py that we handle operator lifecycle externally
export OPERATOR_MANAGED_EXTERNALLY=1
# Tell tests we're running in KIND (skip host-dependent tests)
export KIND_CLUSTER=true
echo "Using Gateway URL: ${GATEWAY_URL}"

# Clean up any leftover test namespaces from previous runs
echo "Cleaning up leftover test namespaces..."
kubectl get ns -o name | grep -E "e2e-(gw[0-9]+|main)" | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
sleep 2

# Run tests using operator Makefile target
echo ""
echo "=== Running E2E tests ==="
cd "${OPERATOR_ROOT}"
make e2e-test
