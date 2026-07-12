# Live authorization validation

This walkthrough reproduces the gateway authorization checks with real JWTs and HTTP requests. It uses a KIND cluster with Calico because the default KIND CNI does not enforce Kubernetes `NetworkPolicy`.

Run every command from the KAOS repository root. The examples use the `kaos-manual-e2e` cluster and keep it running when finished.

## Create the Calico cluster

```bash
mkdir -p tmp
cat > tmp/manual-e2e-kind.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  podSubnet: 192.168.0.0/16
nodes:
  - role: control-plane
EOF

kind create cluster --name kaos-manual-e2e --config tmp/manual-e2e-kind.yaml
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/tigera-operator.yaml
kubectl wait --for=condition=Established crd/installations.operator.tigera.io --timeout=180s
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/custom-resources.yaml
kubectl wait --for=condition=Available tigerastatus/calico --timeout=600s
kubectl wait --for=condition=Ready node --all --timeout=300s
```

Before relying on strict mode, prove the CNI enforces policy by running a baseline pod-to-pod request, applying a default-deny ingress policy, and confirming the same request times out. A present `NetworkPolicy` object is not sufficient evidence by itself.

## Build and load the branch images

```bash
docker build -t axsauze/kaos-operator:manual-e2e operator
docker build --build-context kaos-memory=kaos-memory \
  -t axsauze/kaos-agent:manual-e2e pydantic-ai-server
docker pull openpolicyagent/opa:1.18.1-envoy-static
docker pull ghcr.io/berriai/litellm:main-stable

kind load docker-image \
  axsauze/kaos-operator:manual-e2e \
  axsauze/kaos-agent:manual-e2e \
  openpolicyagent/opa:1.18.1-envoy-static \
  ghcr.io/berriai/litellm:main-stable \
  --name kaos-manual-e2e
```

## Agent plane

Install cluster-issued Agent identity, the in-chart PDP, and strict gateway-only routing:

```bash
uv run --project kaos-cli kaos system install \
  --namespace kaos-system \
  --auth-enabled kaos-internal \
  --gateway-api-strict \
  --gateway-enabled \
  --metallb-enabled \
  --chart-path operator/chart/ \
  --set controllerManager.manager.image.repository=axsauze/kaos-operator \
  --set controllerManager.manager.image.tag=manual-e2e \
  --set controllerManager.manager.imagePullPolicy=IfNotPresent \
  --set defaultImages.agentRuntime=axsauze/kaos-agent:manual-e2e \
  --wait
```

Apply two protected ModelAPIs, an autonomous Agent granted only the first ModelAPI, an unrelated Agent, and a probe pod:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: authz-demo
---
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: granted-model
  namespace: authz-demo
spec:
  mode: Proxy
  proxyConfig:
    models: ["*"]
  container:
    env:
      - name: OPENAI_API_KEY
        value: sk-manual-e2e
---
apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: ungranted-model
  namespace: authz-demo
spec:
  mode: Proxy
  proxyConfig:
    models: ["*"]
  container:
    env:
      - name: OPENAI_API_KEY
        value: sk-manual-e2e
---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: autonomous-researcher
  namespace: authz-demo
spec:
  modelAPI: granted-model
  model: openai/manual-e2e
  waitForDependencies: false
  config:
    instructions: Return a short validation result.
    autonomous:
      goal: Validate the authorized gateway path.
      intervalSeconds: 3600
  container:
    env:
      - name: DEBUG_MOCK_RESPONSES
        value: '["manual e2e complete"]'
  agentNetwork:
    expose: true
---
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: unrelated-agent
  namespace: authz-demo
spec:
  modelAPI: ungranted-model
  model: openai/manual-e2e
  waitForDependencies: false
  config:
    instructions: Return a short validation result.
  container:
    env:
      - name: DEBUG_MOCK_RESPONSES
        value: '["manual e2e complete"]'
  agentNetwork:
    expose: true
---
apiVersion: v1
kind: Pod
metadata:
  name: bypass-client
  namespace: authz-demo
spec:
  containers:
    - name: curl
      image: curlimages/curl:8.12.1
      command: ["sleep", "infinity"]
```

Port-forward the Envoy data-plane Service in a separate terminal:

```bash
ENVOY_SERVICE=$(kubectl get service -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=kaos-gateway \
  -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward -n envoy-gateway-system service/$ENVOY_SERVICE 18888:80
```

Mint a real projected ServiceAccount token and call the gateway:

```bash
TOKEN=$(kubectl create token kaos-agent-autonomous-researcher \
  -n authz-demo --audience=kaos-gateway --duration=10m)

# Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:18888/authz-demo/modelapi/granted-model/health/liveliness

# Expected: 403 (same identity, ungranted target)
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:18888/authz-demo/modelapi/ungranted-model/health/liveliness

# Expected: 403 (actor without the required subject)
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "x-agent-authorization: Bearer $TOKEN" \
  http://127.0.0.1:18888/authz-demo/modelapi/granted-model/health/liveliness

# Expected: 403 (no identity)
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:18888/authz-demo/modelapi/granted-model/health/liveliness

# Expected: 403 (the path wins over the spoofed target header)
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'x-kaos-target-resource: kaos://modelapi/authz-demo/granted-model' \
  http://127.0.0.1:18888/authz-demo/modelapi/ungranted-model/health/liveliness
```

Fail-closed behavior is observable by scaling the PDP to zero. The request must be denied, and it must return 200 again after recovery:

```bash
kubectl scale deployment/kaos-pdp -n kaos-system --replicas=0
kubectl wait --for=delete pod -n kaos-system -l app.kubernetes.io/name=kaos-pdp --timeout=120s
# Repeat the granted curl. Expected: 403.
kubectl scale deployment/kaos-pdp -n kaos-system --replicas=2
kubectl rollout status deployment/kaos-pdp -n kaos-system --timeout=180s
# Repeat the granted curl. Expected: 200.
```

## Bypass prevention

Strict mode creates ingress policies for every protected workload and for the PDP. A direct request carrying a valid token must time out before policy evaluation, while the gateway request remains 200:

```bash
# Expected: curl exit 28 and HTTP 000, never 200.
kubectl exec -n authz-demo bypass-client -- curl -sS -o /dev/null \
  -w 'http=%{http_code} connect=%{time_connect}\n' \
  --connect-timeout 3 --max-time 5 \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  http://modelapi-granted-model:8000/health/liveliness

# Expected: curl exit 28; workloads cannot call the PDP directly.
kubectl exec -n authz-demo bypass-client -- curl -sS -o /dev/null \
  -w 'http=%{http_code} connect=%{time_connect}\n' \
  --connect-timeout 3 --max-time 5 \
  http://kaos-pdp.kaos-system.svc:9191
```

## Keycloak user plane and OIDC Agent DCR

Create a group-based entry grant before enabling `userAuth` and inspect its condition. Under `kaos-internal`, the expected result is `False/NoUserIdentityProvider`:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: AccessGrant
metadata:
  name: researchers-enter-autonomous
  namespace: authz-demo
spec:
  subjects:
    - kind: Group
      name: researchers
  resources:
    - kind: Agent
      name: autonomous-researcher
```

```bash
kubectl get accessgrant researchers-enter-autonomous -n authz-demo \
  -o jsonpath='{.status.conditions[?(@.type=="Enforced")]}{"\n"}'
```

Install the `oidc-keycloak` posture. The operator waits for the DCR bootstrap Secret:

```bash
uv run --project kaos-cli kaos system install \
  --namespace kaos-system \
  --auth-enabled oidc-keycloak \
  --gateway-api-strict \
  --gateway-enabled \
  --chart-path operator/chart/ \
  --set controllerManager.manager.image.repository=axsauze/kaos-operator \
  --set controllerManager.manager.image.tag=manual-e2e \
  --set defaultImages.agentRuntime=axsauze/kaos-agent:manual-e2e
```

Mint the Keycloak initial-access token through the in-cluster service URL. This matters because Keycloak binds the token issuer and audience to the request host; a token minted through a localhost port-forward is rejected by in-cluster DCR with 401:

```bash
KC=http://keycloak.keycloak.svc.cluster.local:8080
ADMIN=$(kubectl exec -n authz-demo bypass-client -- curl -fsS -X POST \
  "$KC/realms/master/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode client_id=admin-cli \
  --data-urlencode username=admin \
  --data-urlencode password=admin \
  --data-urlencode grant_type=password | jq -r .access_token)

IAT=$(kubectl exec -n authz-demo bypass-client -- curl -fsS -X POST \
  "$KC/admin/realms/kaos/clients-initial-access" \
  -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' \
  -d '{"expiration":86400,"count":100}' | jq -r .token)

kubectl create secret generic kaos-oidc-registration -n kaos-system \
  --from-literal=token="$IAT"
kubectl rollout restart deployment/kaos-kaos-operator-controller-manager -n kaos-system
kubectl rollout status deployment/kaos-kaos-operator-controller-manager -n kaos-system
```

After projection, the grant condition becomes `True/Enforced`. Mint the managed Keycloak user token through the same in-cluster URL:

```bash
USER_TOKEN=$(kubectl exec -n authz-demo bypass-client -- curl -fsS -X POST \
  "$KC/realms/kaos/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode client_id=kaos \
  --data-urlencode client_secret=kaos-dev-secret \
  --data-urlencode username=kaos-user \
  --data-urlencode password=kaos-password \
  --data-urlencode grant_type=password | jq -r .access_token)

# Expected: 200 after the projection and ConfigMap-volume delay.
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $USER_TOKEN" \
  http://127.0.0.1:18888/authz-demo/agent/autonomous-researcher/health

# Expected: 403 when no AccessGrant covers the target Agent.
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $USER_TOKEN" \
  http://127.0.0.1:18888/authz-demo/agent/unrelated-agent/health
```

The DCR-created Secret contains the OAuth client credentials. Obtain an Agent token from Keycloak and call the granted resource:

```bash
CLIENT_ID=$(kubectl get secret kaos-oidc-autonomous-researcher -n authz-demo \
  -o jsonpath='{.data.client_id}' | base64 -d)
CLIENT_SECRET=$(kubectl get secret kaos-oidc-autonomous-researcher -n authz-demo \
  -o jsonpath='{.data.client_secret}' | base64 -d)
ACTOR_TOKEN=$(kubectl exec -n authz-demo bypass-client -- curl -fsS -X POST \
  "$KC/realms/kaos/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode grant_type=client_credentials \
  --data-urlencode client_id="$CLIENT_ID" \
  --data-urlencode client_secret="$CLIENT_SECRET" | jq -r .access_token)

# Expected: 200. The token has aud=kaos-gateway and azp=$CLIENT_ID.
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "x-agent-authorization: Bearer $ACTOR_TOKEN" \
  -H "Authorization: Bearer $ACTOR_TOKEN" \
  http://127.0.0.1:18888/authz-demo/modelapi/granted-model/health/liveliness
```

Authorization projection and mounted OPA data are eventually consistent. Allow up to 90 seconds after a grant, issuer, or DCR mapping change before treating an observed denial as final.

## AIB status

The `aib-keycloak` posture remains best effort with the currently available upstream chart. The broker can be made healthy, but KAOS Agent registration is rejected because the upstream API requires at least one permission-set entry while the KAOS projector sends none. The chart used during validation also did not deploy ext_proc, and the broker returned 404 at the discovery path expected by the KAOS consistency check. Keep `oidc-keycloak` as the reproducible end-to-end posture until those contracts are aligned.
