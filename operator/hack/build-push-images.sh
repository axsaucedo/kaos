#!/bin/bash
# Build images and load into KIND cluster for E2E tests.
# This script is used by both run-e2e-tests.sh and GitHub Actions.
#
# Required environment variables:
#   REGISTRY - Image prefix (e.g., axsauze)
#   KIND_CLUSTER_NAME - KIND cluster name (default: kaos-e2e)
#
# Optional environment variables (with defaults matching chart/values.yaml):
#   OPERATOR_TAG - Tag for operator image (default: from VERSION file)
#   AGENT_TAG - Tag for agent image (default: from VERSION file)
#   LITELLM_IMAGE - Full LiteLLM image tag (default: ghcr.io/berriai/litellm:main-stable)
#   OLLAMA_IMAGE - Full Ollama image (default: alpine/ollama:latest)
#
# Note: LiteLLM is built from our minimal Dockerfile (~200MB) and tagged to override
# the upstream image (1.5GB). This keeps the same image reference in values.yaml.
set -o errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPERATOR_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${OPERATOR_ROOT}/.." && pwd)"

# Read version from VERSION file
DEFAULT_VERSION="$(cat "${PROJECT_ROOT}/VERSION" 2>/dev/null || echo "dev")"

# Validate required variables
if [ -z "${REGISTRY}" ]; then
    echo "ERROR: REGISTRY environment variable is required"
    exit 1
fi

# Set defaults (matching chart/values.yaml)
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-kaos-e2e}"
OPERATOR_TAG="${OPERATOR_TAG:-${DEFAULT_VERSION}}"
AGENT_TAG="${AGENT_TAG:-${DEFAULT_VERSION}}"
LITELLM_IMAGE="${LITELLM_IMAGE:-ghcr.io/berriai/litellm:main-stable}"
OLLAMA_IMAGE="${OLLAMA_IMAGE:-alpine/ollama:latest}"

echo "Building images..."
echo "  REGISTRY: ${REGISTRY}"
echo "  KIND_CLUSTER_NAME: ${KIND_CLUSTER_NAME}"
echo "  OPERATOR_TAG: ${OPERATOR_TAG}"
echo "  AGENT_TAG: ${AGENT_TAG}"
echo "  LITELLM_IMAGE: ${LITELLM_IMAGE}"
echo "  OLLAMA_IMAGE: ${OLLAMA_IMAGE}"
echo ""

# Build operator
echo "Building operator image..."
docker build -t "${REGISTRY}/kaos-operator:${OPERATOR_TAG}" "${OPERATOR_ROOT}/"

# Build agent runtime
echo "Building agent runtime image..."
docker build -t "${REGISTRY}/kaos-agent:${AGENT_TAG}" "${PROJECT_ROOT}/python/"

# Tag same image for MCP server (they use the same base)
docker tag "${REGISTRY}/kaos-agent:${AGENT_TAG}" "${REGISTRY}/kaos-mcp-server:${AGENT_TAG}"

# Build minimal LiteLLM image (~200MB vs 1.5GB upstream)
# Tag it as the upstream image to override for local development
echo "Building minimal LiteLLM image..."
docker build -t "${LITELLM_IMAGE}" -f "${SCRIPT_DIR}/Dockerfile.litellm" "${SCRIPT_DIR}"

# Pull Ollama image
echo "Pulling Ollama image..."
docker pull "${OLLAMA_IMAGE}"

# Load images into KIND cluster
echo ""
echo "Loading images into KIND cluster '${KIND_CLUSTER_NAME}'..."
kind load docker-image "${REGISTRY}/kaos-operator:${OPERATOR_TAG}" --name "${KIND_CLUSTER_NAME}"
kind load docker-image "${REGISTRY}/kaos-agent:${AGENT_TAG}" --name "${KIND_CLUSTER_NAME}"
kind load docker-image "${REGISTRY}/kaos-mcp-server:${AGENT_TAG}" --name "${KIND_CLUSTER_NAME}"
kind load docker-image "${LITELLM_IMAGE}" --name "${KIND_CLUSTER_NAME}"
kind load docker-image "${OLLAMA_IMAGE}" --name "${KIND_CLUSTER_NAME}"

echo ""
echo "All images built and loaded into KIND!"
