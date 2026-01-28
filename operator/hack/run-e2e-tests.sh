#!/bin/bash
# Runs E2E tests in KIND cluster.
# This script sets up port-forwarding and runs tests.
# The operator must already be installed via `make kind-e2e-install-kaos`.
#
# Prerequisites (run these before this script):
#   - make kind-create           - Create KIND cluster with Gateway and MetalLB
#   - make kind-load-images      - Build and load images into KIND
#   - make kind-e2e-install-kaos - Generate Helm values and install operator
#
# Or use: make kind-e2e-run-tests (runs load-images, install-kaos, then this script)
set -o errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPERATOR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${OPERATOR_ROOT}/.." && pwd)"

# Configuration
export KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-kaos-e2e}"
HELM_VALUES_FILE="${SCRIPT_DIR}/kind-e2e-values.yaml"

# Check prerequisites
echo "=== Checking prerequisites ==="

# Check KIND cluster exists
if ! kind get clusters 2>/dev/null | grep -q "^${KIND_CLUSTER_NAME}$"; then
    echo "ERROR: KIND cluster '${KIND_CLUSTER_NAME}' not found."
    echo "Run: make kind-create"
    exit 1
fi
echo "✓ KIND cluster '${KIND_CLUSTER_NAME}' exists"

# Check Helm values file exists (created by kind-e2e-install-kaos)
if [ ! -f "${HELM_VALUES_FILE}" ]; then
    echo "ERROR: Helm values file not found: ${HELM_VALUES_FILE}"
    echo "Run: make kind-e2e-install-kaos"
    exit 1
fi
echo "✓ Helm values file exists"

# Check images are loaded (spot check operator image)
REGISTRY="${REGISTRY:-kind-local}"
DEFAULT_VERSION="$(cat "${PROJECT_ROOT}/VERSION" 2>/dev/null || echo "dev")"
OPERATOR_TAG="${OPERATOR_TAG:-${DEFAULT_VERSION}}"
if ! docker exec "${KIND_CLUSTER_NAME}-control-plane" crictl images 2>/dev/null | grep -q "${REGISTRY}/kaos-operator"; then
    echo "ERROR: Operator image not found in KIND cluster."
    echo "Run: make kind-load-images"
    exit 1
fi
echo "✓ Images loaded in KIND"

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

# Check operator is installed
if ! helm status kaos -n kaos-system >/dev/null 2>&1; then
    echo "ERROR: Operator not installed."
    echo "Run: make kind-e2e-install-kaos"
    exit 1
fi
echo "✓ Operator is installed"

# Wait for Gateway to be programmed
echo "Waiting for Gateway to be programmed..."
for i in {1..30}; do
    STATUS=$(kubectl get gateway kaos-gateway -n kaos-system -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}' 2>/dev/null || echo "")
    if [ "$STATUS" = "True" ]; then
        echo "Gateway is programmed!"
        break
    fi
    echo "Waiting for Gateway... (attempt $i/30)"
    sleep 2
done

# Get the Envoy Gateway service for port-forwarding
GATEWAY_SVC=$(kubectl get svc -n envoy-gateway-system -l "gateway.envoyproxy.io/owning-gateway-name=kaos-gateway" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
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
    helm uninstall kaos -n kaos-system 2>/dev/null || true
    kubectl delete namespace kaos-system --wait=false 2>/dev/null || true
    
    # Clean up leftover test namespaces
    kubectl get ns -o name | grep -E "e2e-(gw[0-9]+|main)" | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
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
