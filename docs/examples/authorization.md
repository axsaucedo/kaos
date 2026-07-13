---
jupyter:
  jupytext:
    cell_metadata_filter: -all
    text_representation:
      extension: .md
      format_name: markdown
      format_version: '1.3'
      jupytext_version: 1.19.1
  kernelspec:
    display_name: Python 3 (ipykernel)
    language: python
    name: python3
---

# Gateway Authorization

This example proves that an autonomous Agent needs both a valid actor identity and the required subject identity before it can reach a granted resource. The executable section covers the ServiceAccount agent plane: a granted request succeeds, ungranted and malformed identities are denied, and the gateway fails closed when the policy decision point (PDP) is unavailable.

The later user-plane and gateway-bypass sections are read-only examples. They show the complete Keycloak, OIDC dynamic client registration (DCR), and Calico strict-routing flow, but Jupytext does not run them in CI.

## Agent plane: executed in CI

Install KAOS with gateway authorization backed by projected Kubernetes ServiceAccount tokens:

```bash
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
kaos system install --gateway-enabled --metallb-enabled \
  --agent-auth-enabled service-account \
  --chart-path "$REPO_ROOT/operator/chart" --wait
```

Apply the self-contained sample and wait for its workloads. The autonomous Agent is granted only `granted-model`; `unrelated-agent` exists to make the deny side visible.

```bash
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
kubectl apply -f "$REPO_ROOT/operator/config/samples/8-access-grant.yaml"

kubectl wait --for=condition=available deployment/modelapi-granted-model \
  -n authz-demo --timeout=180s
kubectl wait --for=condition=available deployment/modelapi-ungranted-model \
  -n authz-demo --timeout=180s
kubectl wait --for=condition=available deployment/agent-autonomous-researcher \
  -n authz-demo --timeout=180s
kubectl wait --for=condition=available deployment/agent-unrelated-agent \
  -n authz-demo --timeout=180s
```

Mint a short-lived projected token with the gateway audience, port-forward Envoy, and assert the authorization matrix. The first request retries while the policy projection settles; every other request checks the returned status immediately.

```bash
set -euo pipefail

assert_status() {
  expected=$1
  description=$2
  shift 2
  code=$(curl -sS -o /dev/null -w '%{http_code}' "$@" || true)
  [ "$code" = "$expected" ] || {
    echo "$description: expected $expected got $code"
    exit 1
  }
  echo "$description: $code"
}

wait_for_status() {
  expected=$1
  description=$2
  shift 2
  for _ in $(seq 1 60); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' "$@" || true)
    if [ "$code" = "$expected" ]; then
      echo "$description: $code"
      return 0
    fi
    sleep 2
  done
  echo "$description: expected $expected got $code"
  return 1
}

ENVOY_SERVICE=$(kubectl get service -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=kaos-gateway \
  -o jsonpath='{.items[0].metadata.name}')
GATEWAY_URL=http://127.0.0.1:18888
TMP_DIR=$(git rev-parse --show-toplevel)/tmp
mkdir -p "$TMP_DIR"
ORIGINAL_PDP_REPLICAS=$(kubectl get deployment/kaos-pdp -n kaos-system \
  -o jsonpath='{.spec.replicas}')

kubectl port-forward -n envoy-gateway-system \
  "service/$ENVOY_SERVICE" 18888:80 >"$TMP_DIR/authorization-port-forward.log" 2>&1 &
PORT_FORWARD_PID=$!
cleanup() {
  kubectl scale deployment/kaos-pdp -n kaos-system \
    --replicas="${ORIGINAL_PDP_REPLICAS:-2}" >/dev/null 2>&1 || true
  kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  curl -s -o /dev/null "$GATEWAY_URL" && break
  sleep 1
done
kill -0 "$PORT_FORWARD_PID"

TOKEN=$(kubectl create token kaos-agent-autonomous-researcher \
  -n authz-demo --audience=kaos-gateway --duration=10m)
WRONG_AUDIENCE_TOKEN=$(kubectl create token kaos-agent-autonomous-researcher \
  -n authz-demo --audience=not-kaos-gateway --duration=10m)

GRANTED_URL="$GATEWAY_URL/authz-demo/modelapi/granted-model/health/liveliness"
UNGRANTED_URL="$GATEWAY_URL/authz-demo/modelapi/ungranted-model/health/liveliness"

wait_for_status 200 "granted resource" \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  "$GRANTED_URL"
assert_status 403 "ungranted resource" \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  "$UNGRANTED_URL"
assert_status 403 "missing subject" \
  -H "x-agent-authorization: Bearer $TOKEN" \
  "$GRANTED_URL"
assert_status 403 "wrong-audience token" \
  -H "x-agent-authorization: Bearer $WRONG_AUDIENCE_TOKEN" \
  -H "Authorization: Bearer $WRONG_AUDIENCE_TOKEN" \
  "$GRANTED_URL"

kubectl scale deployment/kaos-pdp -n kaos-system --replicas=0
kubectl wait --for=delete pod -n kaos-system \
  -l app.kubernetes.io/name=kaos-pdp --timeout=120s
wait_for_status 403 "PDP unavailable" \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  "$GRANTED_URL"

kubectl scale deployment/kaos-pdp -n kaos-system \
  --replicas="${ORIGINAL_PDP_REPLICAS:-2}"
kubectl rollout status deployment/kaos-pdp -n kaos-system --timeout=180s
wait_for_status 200 "PDP restored" \
  -H "x-agent-authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer $TOKEN" \
  "$GRANTED_URL"
```

The important distinction is the two headers: `x-agent-authorization` identifies the calling Agent, while `Authorization` supplies the subject on whose behalf it acts. For an autonomous Agent, both can carry the same projected identity, but omitting the subject is still denied.

## Full Keycloak user and agent planes

The remaining cells are intentionally marked `.noeval`: they are rendered for readers but skipped by CI. Start with a Calico KIND cluster because Kubernetes `NetworkPolicy` objects only prove gateway-only routing when the cluster CNI enforces them.

```bash .noeval
mkdir -p tmp
cat > tmp/authz-kind.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  podSubnet: 192.168.0.0/16
nodes:
  - role: control-plane
EOF

kind create cluster --name kaos-authz --config tmp/authz-kind.yaml
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/tigera-operator.yaml
kubectl wait --for=condition=Established crd/installations.operator.tigera.io --timeout=180s
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/custom-resources.yaml
kubectl wait --for=condition=Available tigerastatus/calico --timeout=600s
kubectl wait --for=condition=Ready node --all --timeout=300s
```

First create the grant without a user identity provider. Its `Enforced` condition is `False/NoUserIdentityProvider`; the grant cannot affect policy until the user plane exists.

```bash .noeval
set -euo pipefail
kaos system install --gateway-enabled --metallb-enabled --gateway-api-strict \
  --agent-auth-enabled service-account --user-auth-enabled none --wait
kubectl apply -f operator/config/samples/8-access-grant.yaml
kubectl run bypass-client -n authz-demo --image=curlimages/curl:8.12.1 \
  --command -- sleep infinity
kubectl wait --for=condition=Ready pod/bypass-client -n authz-demo --timeout=120s

condition=$(kubectl get accessgrant researchers-enter-autonomous -n authz-demo \
  -o jsonpath='{.status.conditions[?(@.type=="Enforced")].status}/{.status.conditions[?(@.type=="Enforced")].reason}')
[ "$condition" = "False/NoUserIdentityProvider" ] || {
  echo "expected False/NoUserIdentityProvider got $condition"
  exit 1
}
```

Upgrade to Keycloak for both planes. The operator waits for an initial-access token before it can dynamically register Agent clients, so mint that token through Keycloak's in-cluster hostname, create the bootstrap Secret, and restart the operator.

```bash .noeval
set -euo pipefail
kaos system install --gateway-enabled --metallb-enabled --gateway-api-strict \
  --agent-auth-enabled keycloak --user-auth-enabled keycloak

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
kubectl rollout status deployment/kaos-kaos-operator-controller-manager \
  -n kaos-system --timeout=180s

for _ in $(seq 1 45); do
  condition=$(kubectl get accessgrant researchers-enter-autonomous -n authz-demo \
    -o jsonpath='{.status.conditions[?(@.type=="Enforced")].status}/{.status.conditions[?(@.type=="Enforced")].reason}')
  [ "$condition" = "True/Enforced" ] && break
  sleep 2
done
[ "$condition" = "True/Enforced" ] || {
  echo "expected True/Enforced got $condition"
  exit 1
}
```

Port-forward Envoy as in the executed section. The managed `kaos-user` belongs to `researchers`, so its user token can enter the granted Agent but not the unrelated one.

```bash .noeval
set -euo pipefail
ENVOY_SERVICE=$(kubectl get service -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=kaos-gateway \
  -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward -n envoy-gateway-system \
  "service/$ENVOY_SERVICE" 18888:80 >tmp/authorization-keycloak-port-forward.log 2>&1 &
GATEWAY_URL=http://127.0.0.1:18888

USER_TOKEN=$(kubectl exec -n authz-demo bypass-client -- curl -fsS -X POST \
  "$KC/realms/kaos/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode client_id=kaos \
  --data-urlencode client_secret=kaos-dev-secret \
  --data-urlencode username=kaos-user \
  --data-urlencode password=kaos-password \
  --data-urlencode grant_type=password | jq -r .access_token)

code=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $USER_TOKEN" \
  "$GATEWAY_URL/authz-demo/agent/autonomous-researcher/health")
[ "$code" = "200" ] || { echo "expected entry 200 got $code"; exit 1; }

code=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $USER_TOKEN" \
  "$GATEWAY_URL/authz-demo/agent/unrelated-agent/health")
[ "$code" = "403" ] || { echo "expected ungranted 403 got $code"; exit 1; }
```

Each Agent receives a DCR-created Secret. Exchange those client credentials for an actor token and prove the autonomous Agent still reaches only its granted ModelAPI.

```bash .noeval
set -euo pipefail
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

code=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "x-agent-authorization: Bearer $ACTOR_TOKEN" \
  -H "Authorization: Bearer $ACTOR_TOKEN" \
  "$GATEWAY_URL/authz-demo/modelapi/granted-model/health/liveliness")
[ "$code" = "200" ] || { echo "expected DCR actor 200 got $code"; exit 1; }
```

## Prove the gateway cannot be bypassed

Strict mode creates ingress policies for protected workloads and the PDP. A valid token sent directly to either ClusterIP must time out with curl exit code 28, while the same request through Envoy remains allowed.

```bash .noeval
set -euo pipefail
set +e
kubectl exec -n authz-demo bypass-client -- curl -sS -o /dev/null \
  --connect-timeout 3 --max-time 5 \
  -H "x-agent-authorization: Bearer $ACTOR_TOKEN" \
  -H "Authorization: Bearer $ACTOR_TOKEN" \
  http://modelapi-granted-model:8000/health/liveliness
modelapi_rc=$?

kubectl exec -n authz-demo bypass-client -- curl -sS -o /dev/null \
  --connect-timeout 3 --max-time 5 \
  http://kaos-pdp.kaos-system.svc:9191
pdp_rc=$?
set -e

[ "$modelapi_rc" = "28" ] || {
  echo "expected direct ModelAPI timeout (28) got $modelapi_rc"
  exit 1
}
[ "$pdp_rc" = "28" ] || {
  echo "expected direct PDP timeout (28) got $pdp_rc"
  exit 1
}

code=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "x-agent-authorization: Bearer $ACTOR_TOKEN" \
  -H "Authorization: Bearer $ACTOR_TOKEN" \
  "$GATEWAY_URL/authz-demo/modelapi/granted-model/health/liveliness")
[ "$code" = "200" ] || { echo "expected gateway 200 got $code"; exit 1; }
```

Authorization projection and mounted OPA data are eventually consistent. After a grant, issuer, or DCR mapping changes, allow up to 90 seconds for the new policy to appear before treating a denial as final.

## Delegated access to a third-party service

This final walkthrough is also `.noeval`. It mirrors the passing wire evaluation with Keycloak 26, an AIB release whose chart includes ext_proc, and a mock OAuth provider/API. CI renders it without creating that heavy stack. The example assumes an Agent named `researcher` has an `httpx` tool that calls `http://github-mock-egress.token-exchange-demo.svc.cluster.local/api/data`.

Install the self-managed AIB release and KAOS token-exchange integration. The two feature flags that matter here are `--token-exchange-enabled` and `--aib-chart-path`; token exchange also requires Keycloak for both user and Agent identity.

```bash .noeval
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
kaos system install --gateway-enabled --metallb-enabled \
  --agent-auth-enabled keycloak --user-auth-enabled keycloak \
  --token-exchange-enabled \
  --aib-chart-path ../aib-222-verify/charts/agentic-identity-broker \
  --chart-path "$REPO_ROOT/operator/chart" --wait
```

The managed development Keycloak starts with `token-exchange` and `admin-fine-grained-authz` when that flag is set, but Keycloak 26 still requires explicit target-client setup. Create the `token-exchange-broker` client, enable its management permissions, allow each exchange-enabled Agent DCR client to exchange to it, and add an audience mapper that produces exactly `aud=token-exchange-broker`. Without the features, Keycloak returns `400 unsupported_grant_type`; without the per-client permission, it returns `403 Client not allowed to exchange`.

Create the dedicated egress route, provider OAuth client Secret, and `ThirdPartyService`. This is the manifest shape used in the live evaluation. The example assumes `Service/mock-api` already exposes the mock authorization server and API on port 9000.

```yaml .noeval
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: github-mock-egress
  namespace: token-exchange-demo
spec:
  parentRefs:
    - name: kaos-gateway
      namespace: kaos-system
      sectionName: http
  hostnames:
    - github-mock-egress.token-exchange-demo.svc.cluster.local
  rules:
    - backendRefs:
        - name: mock-api
          port: 9000
---
apiVersion: v1
kind: Secret
metadata:
  name: github-mock-oauth-client
  namespace: token-exchange-demo
type: Opaque
stringData:
  client-secret: mock-third-party-secret
---
apiVersion: kaos.tools/v1alpha1
kind: ThirdPartyService
metadata:
  name: github-mock
  namespace: token-exchange-demo
spec:
  displayName: GitHub Mock
  clientID: mock-third-party-client
  clientSecretRef:
    name: github-mock-oauth-client
    key: client-secret
  issuerURI: http://mock-oauth.token-exchange-demo.svc.cluster.local:9000
  endpoints:
    authorization: http://mock-oauth.token-exchange-demo.svc.cluster.local:9000/oauth/authorize
    token: http://mock-oauth.token-exchange-demo.svc.cluster.local:9000/oauth/token
  scopes:
    - name: read
      description: Read the mock GitHub profile
  protectedResources:
    - http://github-mock-egress.token-exchange-demo.svc.cluster.local/api/data
  routeRef:
    name: github-mock-egress
  access:
    - agent: researcher
      scopes:
        - read
```

```bash .noeval
kubectl create namespace token-exchange-demo
kubectl apply -f github-token-exchange.yaml
kubectl wait thirdpartyservice/github-mock -n token-exchange-demo \
  --for=condition=Ready --timeout=180s
```

Mint the user's normal Keycloak token, then call the Agent. The first call without a live vault session is an application-level HTTP 200 containing the controlled `third_party_reauth_required` result and AIB authorization URL; the third-party tool has not succeeded.

```bash .noeval
USER_TOKEN=$(curl -fsS -X POST \
  "$KEYCLOAK_URL/realms/kaos/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode client_id=kaos \
  --data-urlencode client_secret=kaos-dev-secret \
  --data-urlencode username=kaos-user \
  --data-urlencode password="$KAOS_USER_PASSWORD" \
  --data-urlencode grant_type=password | jq -r .access_token)

FIRST_RESULT=$(curl -fsS "$GATEWAY_URL/token-exchange-demo/agent/researcher/v1/chat/completions" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"researcher","messages":[{"role":"user","content":"Call the third-party service"}]}' \
  | jq -r '.choices[0].message.content')
echo "$FIRST_RESULT"
# Access to the requested resource requires re-authentication (third_party_reauth_required).
# Please reconnect at /api/third-party/<service-id>/oauth2/authorize and try again.
```

Open the surfaced URL as that user, complete the provider's S256 PKCE authorization-code flow, and approve the Agent's `read` permission in AIB. The redirect chain finishes at AIB's consent UI with HTTP 200, the vault session is encrypted and has a refresh token, and the UserGrant records the user + Agent + service triple. KAOS does not store the provider token.

```bash .noeval
kubectl port-forward -n aib-system svc/aib-agentic-identity-broker 8000:8000 >./tmp/aib-port-forward.log 2>&1 &
AIB_URL=http://localhost:8000
REAUTH_PATH=$(echo "$FIRST_RESULT" | grep -Eo '/api/third-party/[^ ]+/oauth2/authorize')
open "${AIB_URL}${REAUTH_PATH}"  # use xdg-open on Linux

SUCCESS_RESULT=$(curl -fsS "$GATEWAY_URL/token-exchange-demo/agent/researcher/v1/chat/completions" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"researcher","messages":[{"role":"user","content":"Call the third-party service"}]}' \
  | jq -r '.choices[0].message.content')
echo "$SUCCESS_RESULT"
# Third-party tool completed.
```

The successful wire evaluation returned HTTP 200 at Agent entry and HTTP 200 from `GET /api/data`. The re-minted token accepted by the exchange decoded exactly as follows; `azp` is the `researcher` DCR client, while `sub` remains the requesting user:

```json .noeval
{
  "aud": "token-exchange-broker",
  "azp": "85be1caf-30b9-4236-87b2-fae29613d86d",
  "sub": "c9df7bbc-c015-4095-b39e-7b5ed1a3f5e9",
  "iss": "http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos"
}
```

AIB ext_proc exchanges that token for the user's vaulted provider token only on `github-mock-egress`. Internal routes keep the original user token and have no ext_proc attachment.

Finally, terminate the provider session and retry. The delete returns HTTP 200 with `session terminated successfully`; the next Agent call again returns `third_party_reauth_required`, while ext_proc records broker HTTP 400 `invalid_grant`.

```bash .noeval
USER_SUB=$(echo "$USER_TOKEN" | cut -d. -f2 | tr '_-' '/+' | base64 -d 2>/dev/null | jq -r .sub)
SERVICE_ID=$(echo "$REAUTH_PATH" | cut -d/ -f4)

curl -fsS -X DELETE "$AIB_URL/api/third-party/$SERVICE_ID/session" \
  -H "X-Remote-User: $USER_SUB"
# {"message":"session terminated successfully"}

curl -fsS "$GATEWAY_URL/token-exchange-demo/agent/researcher/v1/chat/completions" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"researcher","messages":[{"role":"user","content":"Call the third-party service"}]}' \
  | jq -r '.choices[0].message.content'
# Access to the requested resource requires re-authentication (third_party_reauth_required).
# Please reconnect at /api/third-party/<service-id>/oauth2/authorize and try again.
```

`X-Remote-User` above matches the evaluation-only AIB pre-auth configuration. A production AIB deployment must authenticate the user at this endpoint instead of trusting a caller-supplied header.
