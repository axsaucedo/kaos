#!/bin/bash
# Installs MetalLB for LoadBalancer support in KIND clusters.
# Works on both local machines and GitHub Actions.
set -o errexit

echo "Installing MetalLB..."
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.9/config/manifests/metallb-native.yaml

echo "Waiting for MetalLB pods to be ready..."
kubectl wait --namespace metallb-system \
  --for=condition=ready pod \
  --selector=app=metallb \
  --timeout=120s

# Get the KIND network subnet - works with both IPv4-only and dual-stack networks
echo "Configuring MetalLB IP address pool..."

# Use jq if available for robust JSON parsing, otherwise fall back to simpler approach
if command -v jq &> /dev/null; then
    # Robust approach: filter IPv4 subnets, handle different IPAM structures
    ADDRESS_RANGE_PREFIX=$(docker network inspect -f json kind | jq -r '
        .[0].IPAM.Config 
        | map(select(.Subnet | test("^[0-9]+\\."))) 
        | .[0].Subnet 
        | split("/")[0] 
        | split(".")[:3] 
        | join(".")
    ')
else
    # Simple fallback using basic Docker format
    KIND_NET_CIDR=$(docker network inspect kind -f '{{(index .IPAM.Config 0).Subnet}}')
    ADDRESS_RANGE_PREFIX=$(echo ${KIND_NET_CIDR} | sed "s@0.0/16@255@" | sed "s@\.[0-9]*/[0-9]*@@")
fi

METALLB_IP_START="${ADDRESS_RANGE_PREFIX}.200"
METALLB_IP_END="${ADDRESS_RANGE_PREFIX}.250"

echo "Using IP range: ${METALLB_IP_START}-${METALLB_IP_END}"

cat <<EOF | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: kind-pool
  namespace: metallb-system
spec:
  addresses:
  - ${METALLB_IP_START}-${METALLB_IP_END}
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: kind-l2
  namespace: metallb-system
spec:
  ipAddressPools:
  - kind-pool
EOF

echo ""
echo "MetalLB installed and configured!"
echo "LoadBalancer IP range: ${METALLB_IP_START}-${METALLB_IP_END}"
