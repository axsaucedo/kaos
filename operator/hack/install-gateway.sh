#!/bin/bash
# Installs Gateway API CRDs and Envoy Gateway controller for E2E testing.
set -o errexit

GATEWAY_API_VERSION="${GATEWAY_API_VERSION:-v1.4.1}"
ENVOY_GATEWAY_VERSION="${ENVOY_GATEWAY_VERSION:-v1.4.6}"

echo "Installing Gateway API CRDs (${GATEWAY_API_VERSION})..."
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"

echo "Waiting for Gateway API CRDs..."
kubectl wait --for condition=established --timeout=60s crd/gateways.gateway.networking.k8s.io
kubectl wait --for condition=established --timeout=60s crd/httproutes.gateway.networking.k8s.io
kubectl wait --for condition=established --timeout=60s crd/gatewayclasses.gateway.networking.k8s.io

echo "Installing Envoy Gateway (${ENVOY_GATEWAY_VERSION})..."
helm upgrade --install envoy-gateway oci://docker.io/envoyproxy/gateway-helm \
  --version "${ENVOY_GATEWAY_VERSION}" \
  --namespace envoy-gateway-system --create-namespace \
  --skip-crds \
  --wait --timeout 120s

echo "Creating GatewayClass..."
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: envoy-gateway
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
EOF

echo "Waiting for GatewayClass to be accepted..."
for i in {1..30}; do
  STATUS=$(kubectl get gatewayclass envoy-gateway -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}' 2>/dev/null || echo "Unknown")
  if [ "$STATUS" = "True" ]; then
    echo "GatewayClass accepted!"
    break
  fi
  echo "Waiting for GatewayClass... (attempt $i/30)"
  sleep 2
done

# Verify GatewayClass is accepted
STATUS=$(kubectl get gatewayclass envoy-gateway -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}' 2>/dev/null || echo "Unknown")
if [ "$STATUS" != "True" ]; then
  echo "ERROR: GatewayClass not accepted after 60 seconds"
  kubectl get gatewayclass envoy-gateway -o yaml
  exit 1
fi

echo ""
echo "Gateway API and Envoy Gateway installed successfully!"
