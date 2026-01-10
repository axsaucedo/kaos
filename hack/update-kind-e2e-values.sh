#!/bin/bash
# Generates the hack/kind-e2e-values.yaml file with specified image versions.
# This file is NOT checked in - it's generated at build time.
# Usage: ./hack/update-kind-e2e-values.sh [--operator-tag TAG] [--agent-tag TAG] [--litellm-version VER] [--ollama-version VER]
set -o errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALUES_FILE="${SCRIPT_DIR}/kind-e2e-values.yaml"

# Default versions (single source of truth)
OPERATOR_TAG="${OPERATOR_TAG:-dev}"
AGENT_TAG="${AGENT_TAG:-dev}"
LITELLM_VERSION="${LITELLM_VERSION:-v1.56.5}"
# alpine/ollama only has 'latest' tag
OLLAMA_TAG="${OLLAMA_TAG:-latest}"
REGISTRY="${REGISTRY:-localhost:5001}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --operator-tag) OPERATOR_TAG="$2"; shift 2 ;;
        --agent-tag) AGENT_TAG="$2"; shift 2 ;;
        --litellm-version) LITELLM_VERSION="$2"; shift 2 ;;
        --ollama-tag) OLLAMA_TAG="$2"; shift 2 ;;
        --registry) REGISTRY="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

cat > "${VALUES_FILE}" << EOF
# Helm values for KIND E2E testing
# This file is used by hack/run-e2e-tests.sh to configure the operator
# with images from the local KIND registry.
#
# To update image versions, edit this file or run:
#   make update-kind-values
#
# Image version conventions:
#   - agentic-*: Use 'dev' tag for local builds
#   - litellm: Use specific version matching Dockerfile.litellm
#   - ollama: alpine/ollama only has 'latest' tag

controllerManager:
  manager:
    image:
      repository: ${REGISTRY}/agentic-operator
      tag: ${OPERATOR_TAG}
    imagePullPolicy: Always

defaultImages:
  agentRuntime: ${REGISTRY}/agentic-agent:${AGENT_TAG}
  mcpServer: ${REGISTRY}/agentic-mcp-server:${AGENT_TAG}
  litellm: ${REGISTRY}/litellm:${LITELLM_VERSION}
  ollama: ${REGISTRY}/ollama:${OLLAMA_TAG}
EOF

echo "Updated ${VALUES_FILE} with:"
echo "  operator: ${REGISTRY}/agentic-operator:${OPERATOR_TAG}"
echo "  agent: ${REGISTRY}/agentic-agent:${AGENT_TAG}"
echo "  litellm: ${REGISTRY}/litellm:${LITELLM_VERSION}"
echo "  ollama: ${REGISTRY}/ollama:${OLLAMA_TAG}"
