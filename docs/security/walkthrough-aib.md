# End-to-end walkthrough: `aib-keycloak` preset

This walkthrough stands up KAOS with the broker-backed `aib-keycloak` security posture — the default, production-shaped posture — and verifies, step by step, that user identity, agent identity, authorization, and gateway-only routing take effect. Every step lists what it proves, and each check can be run from the command line or observed in the KAOS UI.

Unlike the self-contained [`kaos-internal` walkthrough](./walkthrough-kaos), this posture wires KAOS to two external identity components:

- **Keycloak** as the OpenID Connect provider for **user** identity.
- The **Agentic Identity Broker (AIB)** as the issuer of signature-verified **agent** credentials and the enforcement engine (OPA embedded in an Envoy `ext_proc` sidecar).

The seam is deliberate: KAOS owns agent identity and topology, Keycloak owns user identity, and AIB owns authorization. A user's request carries a Keycloak-issued subject token; the calling agent carries a broker-issued actor token; the gateway `ext_proc` hook evaluates both against the agent's granted permission sets.

## What you will verify

1. The `aib-keycloak` preset expands into the operator's `aib` authorization provider with signature-verified agent tokens.
2. Keycloak is installed and bootstrapped with the `kaos` realm for user identity.
3. The AIB broker is installed and the operator registers agents and mints per-agent broker credentials.
4. Each agent reaches other resources **through the gateway**, and its identity is a broker-verified JWT.
5. `SecurityPolicy` (wiring `ext_proc`) and `NetworkPolicy` (bypass prevention) objects are generated.

## Prerequisites

- A Kubernetes cluster with Gateway API and a LoadBalancer (a local KIND cluster with `--gateway-enabled --metallb-enabled` is fine).
- The `kaos` CLI installed (`pip install kaos-cli`).
- `kubectl` pointed at the cluster.
- The AIB broker Helm chart available locally (it is unpublished, so a chart path is required). The `aib-keycloak` preset auto-wires the broker values for token exchange — no hand-written values file is needed.
- On KIND, the operator, agent, and broker images loaded into the cluster (`kind load docker-image ...`).

::: tip NetworkPolicy enforcement
As with `kaos-internal`, the generated `NetworkPolicy` objects are only *enforced* by a NetworkPolicy-capable CNI (for example Calico). The default KIND CNI (kindnet) creates them without enforcing them, which is fine for exploring authorization and routing.
:::

## Reproducible variables

Every command below uses these shell variables so you can copy-paste each step verbatim. The credentials are the fixed dev defaults the `aib-keycloak` preset seeds into Keycloak — they are demo-only, not for real use. Set them once in your shell:

```bash
# Namespaces
export KAOS_NS=kaos-system
export AIB_NS=aib-system
export KC_NS=keycloak
export APP_NS=kaos-walkthrough

# AIB broker chart (unpublished — point at your local clone)
export AIB_CHART=<path-to>/charts/agentic-identity-broker

# Keycloak realm + demo user identity (seeded by the preset)
export REALM=kaos
export KC_USER=kaos-user
export KC_PASSWORD=kaos-password
export USER_CLIENT_ID=kaos
export USER_CLIENT_SECRET=kaos-dev-secret

# Token-exchange gateway client + broker audience (seeded by the preset)
export EXTPROC_CLIENT_ID=extproc-gateway
export EXTPROC_CLIENT_SECRET=extproc-gateway-secret
export TX_AUDIENCE=token-exchange-broker

# In-cluster endpoints
export KC_ISSUER=http://keycloak.${KC_NS}.svc.cluster.local:8080/realms/${REALM}
export BROKER_TOKEN_URL=http://aib-agentic-identity-broker.${AIB_NS}.svc.cluster.local:8000/oauth2/token
```

::: tip Where these values come from
The realm, user, client, secret, and audience are baked into the CLI as the `aib-keycloak` preset defaults. You can confirm them at any time from the seeded realm-import ConfigMap:

```bash
kubectl get configmap keycloak-realm-import -n "$KC_NS" \
  -o jsonpath='{.data}' | python3 -m json.tool | grep -iE 'username|value|clientId|secret'
```
:::

## Step 1 — Install with the `aib-keycloak` preset

Install KAOS with the default `aib-keycloak` preset, pointing at the broker chart. The CLI installs the operator, the AIB broker (into `aib-system`), and Keycloak (into `keycloak`, bootstrapping the `kaos` realm). The preset auto-wires the broker into hybrid mode against Keycloak and enables the token-exchange sidecar — see [Token exchange](#token-exchange-rfc-8693) below:

```bash
kaos system install \
  --namespace "$KAOS_NS" \
  --auth-enabled aib-keycloak \
  --gateway-enabled --metallb-enabled \
  --aib-chart-path "$AIB_CHART" \
  --wait
```

The three presets differ only in the identity and verification layers:

| Preset | User identity | Agent token | Authorization provider |
|--------|---------------|-------------|------------------------|
| `kaos-internal` | none | header-trusted (spoofable, demo only) | `kaos` (grants projected from CRDs) |
| `aib-only` | none | broker-issued, signature-verified | `aib` (broker permission sets) |
| `aib-keycloak` (default) | Keycloak + token exchange | broker-issued, signature-verified | `aib` (broker permission sets) |

**Proves:** a single preset provisions the full broker-backed posture instead of a large set of auth flags.

### Verify the operator picked up the configuration

```bash
kubectl get configmap kaos-operator-config -n "$KAOS_NS" -o json \
  | jq -r '.data | to_entries[] | select(.key | test("SECURITY|AUTHZ|GATEWAY")) | "\(.key)=\(.value)"'
```

Expected keys for `aib-keycloak`:

```
SECURITY_AUTHORIZATION_PROVIDER=aib
SECURITY_AUTHORIZATION_AGENT_JWT_VERIFICATION=verified
SECURITY_AUTHORIZATION_GATEWAY_EXTENSION=ext_proc
SECURITY_AGENT_AUTH_ISSUER=http://aib-agentic-identity-broker.aib-system.svc.cluster.local:8000
SECURITY_AGENT_AUTH_EXT_PROC_URL=aib-agentic-identity-broker-extproc.aib-system.svc.cluster.local:50051
SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX=kaos-aib
SECURITY_USER_AUTH_ISSUER=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos
SECURITY_USER_AUTH_AUDIENCE=kaos
SECURITY_GATEWAY_ROUTING_ENABLED=true
```

**Proves:** the preset baked in the `aib` provider, signature-verified agent tokens, the broker issuer/`ext_proc` endpoints, and the Keycloak user-auth issuer — no extra flags were needed.

## Step 2 — Confirm the identity components are running

```bash
kubectl get pods -n "$AIB_NS"       # AIB broker (+ ext_proc sidecar)
kubectl get pods -n "$KC_NS"        # Keycloak
kubectl get pods -n "$KAOS_NS"      # operator
```

Confirm the Keycloak realm was bootstrapped:

```bash
kubectl logs -n "$KC_NS" deploy/keycloak | grep -i "realm '$REALM'"
```

**Proves:** the broker (agent identity + authorization) and Keycloak (user identity) are both live and the `kaos` realm exists.

## Step 3 — Deploy resources and confirm broker credential minting

Deploy a small topology, then confirm the operator registered each agent with the broker and minted a per-agent credential Secret:

```bash
kubectl create namespace "$APP_NS"
kubectl apply -n "$APP_NS" -f \
  https://raw.githubusercontent.com/axsaucedo/kaos/main/operator/config/samples/2-multi-agent-mcp.yaml
```

Unlike `kaos-internal` (where the agent token is header-trusted), each agent here is issued a real broker credential. The operator's projection controller labels the Secrets it manages with `app.kubernetes.io/managed-by=kaos-operator-authz`. List them and read one:

```bash
kubectl get secret -n "$APP_NS" -l app.kubernetes.io/managed-by=kaos-operator-authz
kubectl get secret kaos-aib-coordinator -n "$APP_NS" \
  -o jsonpath='{.data.client_id}' | base64 -d; echo
```

Each Secret holds the agent's broker `client_id` and `client_secret`. The agent runtime mounts them (as `AGENT_AUTH_CLIENT_ID` / `AGENT_AUTH_CLIENT_SECRET`) and uses them to mint a signed actor-token JWT via OAuth2 `client_credentials` against the broker.

**Proves:** agent identity is broker-backed and cryptographically real, not self-asserted.

::: tip No Secrets appear?
The operator mints these Secrets only when it is running with the auth configuration. A single-shot `kaos system install --auth-enabled aib-keycloak` starts the operator with that config from the outset, and any later `helm upgrade` that changes the config now rolls the operator automatically (the pod template carries a `checksum/config` annotation). If you enabled auth on an operator that predates that annotation and see no Secrets, force one reload:

```bash
kubectl rollout restart deploy/kaos-kaos-operator-controller-manager -n "$KAOS_NS"
kubectl rollout status  deploy/kaos-kaos-operator-controller-manager -n "$KAOS_NS"
```

Then confirm the projection ran (`failed=0`):

```bash
kubectl logs -n "$KAOS_NS" deploy/kaos-kaos-operator-controller-manager \
  | grep "reconciled authorization projection" | tail -1
```
:::

## Step 4 — Mint a user token from Keycloak

User identity flows from Keycloak. Port-forward Keycloak and request a subject token with the OIDC password grant:

```bash
kubectl port-forward -n "$KC_NS" svc/keycloak 8080:8080 >/dev/null 2>&1 &
sleep 2
USER_TOKEN=$(curl -s -X POST http://localhost:8080/realms/$REALM/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=$USER_CLIENT_ID" \
  -d "client_secret=$USER_CLIENT_SECRET" \
  -d "username=$KC_USER" \
  -d "password=$KC_PASSWORD" \
  | jq -r .access_token)
echo "${USER_TOKEN:0:24}..."   # non-empty JWT prefix
```

This subject token is what a user presents to KAOS. At the gateway it is validated by the `jwt_authn` provider against the Keycloak JWKS before any authorization runs.

**Proves:** user identity is issued and verified against Keycloak, on the same trust root as the rest of the posture.

## Step 5 — Confirm gateway-routed identity and enforcement objects

As with `kaos-internal`, agents reach other resources through the gateway, and the operator generates the enforcement objects:

```bash
kubectl get deploy agent-coordinator -n "$APP_NS" -o json \
  | jq -r '.spec.template.spec.containers[0].env[]
      | select(.name | test("URL|AGENT_AUTH_IDENTITY"))
      | "\(.name)=\(.value)"'

kubectl get securitypolicy,networkpolicy -n "$APP_NS"
```

Every outbound URL routes through the gateway path (the `ext_proc` enforcement point cannot be bypassed), and `AGENT_AUTH_IDENTITY` is the single logical identity that threads the whole system — the actor-token `sub`, the broker agent identity, and the authorization subject.

**Proves:** internal calls are gateway-routed and the `ext_proc` authorization hook plus bypass-prevention NetworkPolicies are in place.

## Step 6 — Prove requests are allowed or rejected at the gateway

The previous steps confirm the objects exist. This step sends real requests through the gateway and observes them being **accepted or rejected** by the `jwt_authn` identity gate. Every agent route carries the two `jwt_authn` providers from its `SecurityPolicy` — `user` (Keycloak subject token in `Authorization`) and `agent` (broker actor token in `x-agent-authorization`) — so a request that presents no valid token for either provider never reaches the workload.

The gateway is a `LoadBalancer` whose MetalLB address is only reachable from inside the KIND network (not from the macOS host), so drive the requests from an in-cluster pod. Grab the gateway address and the agent's route path first:

```bash
export GW_IP=$(kubectl get gateway kaos-gateway -n "$KAOS_NS" -o jsonpath='{.status.addresses[0].value}')
export ROUTE="/$APP_NS/agent/coordinator/"
echo "gateway=$GW_IP route=$ROUTE"
```

Mint a fresh user token (Step 4 leaves `USER_TOKEN` set; re-run that step if your shell has expired it), then send four requests from a throwaway curl pod — three that must be **rejected** and one that must be **admitted**:

```bash
kubectl -n "$APP_NS" run authz-demo --rm -i --restart=Never --image=curlimages/curl --command -- sh -c '
GW="http://'"$GW_IP$ROUTE"'"
echo "1) no token          -> $(curl -s -o /dev/null -w %{http_code} $GW)"
echo "2) malformed token   -> $(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer not-a-jwt" $GW)"
echo "3) wrong-issuer JWT   -> $(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJldmlsIiwiYXVkIjoia2FvcyJ9.ZmFrZQ" $GW)"
echo "4) valid user token  -> $(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer '"$USER_TOKEN"'" $GW)"
'
```

Expected:

```text
1) no token          -> 401
2) malformed token   -> 401
3) wrong-issuer JWT   -> 401
4) valid user token   -> 500
```

The first three are **rejected by the gateway** before any workload is touched. The fourth **passes the identity gate** (it is no longer a 401) and is handed to the AIB `ext_proc` token-exchange path — which returns `500` here because user→agent consent and the third-party token vault are not wired in this environment (see [What is not yet wired](#what-is-not-yet-wired-consent-vault)). The important signal is the transition from `401` (rejected at identity) to "past identity" for a genuine Keycloak token.

Read the exact reason Envoy recorded for each request from the gateway access log:

```bash
EPOD=$(kubectl get pod -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=kaos-gateway -o name | head -1)
kubectl logs -n envoy-gateway-system "$EPOD" --tail=4 \
  | python3 -c 'import sys,json
for l in sys.stdin:
    try:
        d=json.loads(l); print(d["response_code"], d["response_code_details"])
    except Exception: pass'
```

Expected — the rejections name the precise validation that failed, and the admitted request shows it left `jwt_authn` and hit the `ext_proc` direct response:

```text
401 jwt_authn_access_denied{Jwt_is_missing}
401 jwt_authn_access_denied{Jwt_is_not_in_the_form_of_Header.Payload.Signature_with_two_dots_and_3_sections}
401 jwt_authn_access_denied{Jwt_issuer_is_not_configured}
500 direct_response
```

You can also confirm the NetworkPolicy bypass guard: a pod trying to reach the agent workload directly (not via the gateway) simply hangs/times out, because only gateway traffic is permitted to the agent.

**Proves:** the gateway cryptographically validates the caller's identity — missing, malformed, and untrusted-issuer tokens are rejected with a specific reason, and only a Keycloak-signed token is admitted past the identity gate — and the workload is unreachable except through that gate.

## Token exchange (RFC 8693)

The `aib-keycloak` posture runs the RFC 8693 **token-exchange** path so an agent can call a protected third-party API on behalf of a user: the broker exchanges the user's Keycloak-issued subject token for a vaulted third-party token, gated by the user's consent grant. The broker's `ext_proc` sidecar automates this exchange inline in the Envoy data path.

### How the exchange is wired

The exchange involves two Keycloak-issued JWTs, both signature-verified by the broker against Keycloak's JWKS:

- **`subject_token`** — the user's access token (minted through the agent's OAuth client). Its `sub` claim is the user principal and its `azp` claim is the agent's client_id, which the broker maps to a registered agent via `resolveAgentIdByClientId(subject_token.azp)`.
- **`client_assertion`** — the gateway's own identity, obtained by the `ext_proc` sidecar via a `client_credentials` grant **against Keycloak** (not the broker) using the `extproc-gateway` client.

The broker therefore runs in **hybrid** OAuth2 mode with Keycloak configured as the upstream issuer. Crucially, the sidecar authenticates against **Keycloak**, and the broker validates both tokens against Keycloak's JWKS — the broker never issues these tokens itself in this posture.

### What the `aib-keycloak` preset wires automatically

You do not need to hand-write a values file or run manual Keycloak/`kubectl` steps — the `aib-keycloak` preset provisions the entire hybrid posture:

- **Broker (hybrid mode):** sets `broker.oauth2AuthorizationServer.mode=hybrid` with Keycloak's authorize/token endpoints as the upstream, enables the `urn:ietf:params:oauth:grant-type:token-exchange` grant, and sets `tokenExchange.expectedAudience=token-exchange-broker`.
- **ExtProc sidecar:** enables `extProc`, points its OAuth `issuer` at the Keycloak realm and its `tokenEndpoint` at the broker's exchange endpoint, and enables `allowHttp` for the in-cluster plain-http endpoints.
- **Keycloak realm:** registers the `extproc-gateway` service-account client (secret `extproc-gateway-secret`) and adds a `token-exchange-broker` custom-audience mapper to **both** the user client (`kaos`) and the `extproc-gateway` client, so the `subject_token` and `client_assertion` both carry the audience the broker enforces.

::: warning Temporary ExtProc client-credentials patch (followup F0)
When `extProc.oauth2.clientCredentialsEndpoint` is unset, the sidecar derives its token endpoint as `issuer + /oauth/token`, which is the mock-upstream path and returns `404` against Keycloak (whose path is `/protocol/openid-connect/token`). The stock AIB chart does not template this env var yet, so the CLI applies it as a post-install patch on the sidecar Deployment:

```bash
kubectl -n "$AIB_NS" set env deploy/aib-agentic-identity-broker-extproc \
  EXTPROC_OAUTH2_CLIENT_CREDENTIALS_ENDPOINT=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos/protocol/openid-connect/token
```

The CLI runs this automatically. It is shown here for transparency and to reapply manually if you redeploy the sidecar. Once the endpoint is templated upstream (followup F0), this patch is dropped and the value comes from the chart.
:::

### Register the demo agent and third-party service

The exchange resolves the agent from the user token's `azp` (`resolveAgentIdByClientId`), so a broker agent whose `client_id` equals the user client (`kaos`) must exist, along with a third-party service to exchange for. The operator projects one broker agent per KAOS Agent (each with its own synthetic `client_id`), so for this demo register the `kaos`-client agent and a demo service directly against the broker admin API:

```bash
kubectl port-forward -n "$AIB_NS" svc/aib-agentic-identity-broker 14000:14000 >/dev/null 2>&1 &
sleep 2
ADMIN=http://localhost:14000/api

# 1. Third-party service exposing the protected resource
SERVICE_ID=$(curl -s -X POST $ADMIN/services -H 'Content-Type: application/json' -d '{
  "display_name": "Demo API",
  "client_id": "demo-thirdparty",
  "client_secret": "demo-thirdparty-secret",
  "issuer_uri": "http://demo-idp.local",
  "discovery": {"enable_discovery": false},
  "endpoints": {"token_endpoint": "http://demo-idp.local/token", "authorize_endpoint": "http://demo-idp.local/authorize"},
  "scopes": [{"scope_value": "read", "description": "Read"}],
  "protected_resources": ["https://api.demo.local"]
}' | jq -r .id)

# 2. Permission set granting read on that service
PSET_ID=$(curl -s -X POST $ADMIN/permission-sets -H 'Content-Type: application/json' -d "{
  \"name\": \"demo-read\",
  \"description\": \"Demo read\",
  \"service_scopes\": [{\"service_id\": \"$SERVICE_ID\", \"scopes\": [\"read\"], \"requirement_type\": \"mandatory\"}]
}" | jq -r .id)

# 3. Agent whose client_id matches the user token azp (kaos)
curl -s -X POST $ADMIN/agents -H 'Content-Type: application/json' -d "{
  \"client_id\": \"$USER_CLIENT_ID\",
  \"display_name\": \"KAOS Agent\",
  \"description\": \"KAOS agent for token exchange validation\",
  \"permission_sets\": [{\"permission_set_id\": \"$PSET_ID\", \"requirement_type\": \"mandatory\"}]
}" | jq -r .id

echo "service=$SERVICE_ID pset=$PSET_ID"
```

### Verify the exchange reaches the broker

Run the exchange from inside the cluster (so the token `iss` matches the broker's configured upstream issuer). The credentials below are the preset defaults from [Reproducible variables](#reproducible-variables):

```bash
kubectl -n "$AIB_NS" run tx --rm -i --restart=Never --image=curlimages/curl -- sh -c '
KC=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos/protocol/openid-connect/token
BROKER=http://aib-agentic-identity-broker.aib-system.svc.cluster.local:8000/oauth2/token
SUBJ=$(curl -s -X POST $KC -d grant_type=password -d client_id=kaos -d client_secret=kaos-dev-secret -d username=kaos-user -d password=kaos-password | sed -n "s/.*\"access_token\":\"\([^\"]*\)\".*/\1/p")
ASSERT=$(curl -s -X POST $KC -d grant_type=client_credentials -d client_id=extproc-gateway -d client_secret=extproc-gateway-secret | sed -n "s/.*\"access_token\":\"\([^\"]*\)\".*/\1/p")
curl -s -w "\nHTTP %{http_code}\n" -X POST $BROKER \
  --data-urlencode "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  --data-urlencode "subject_token=$SUBJ" \
  --data-urlencode "subject_token_type=urn:ietf:params:oauth:token-type:jwt" \
  --data-urlencode "client_assertion=$ASSERT" \
  --data-urlencode "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
  --data-urlencode "resource=https://api.demo.local"'
```

A correctly wired install returns:

```json
{"error":"access_denied","error_description":"user has not granted permission for this agent to access the requested service"}
```

This `403` is the **expected** result up to the consent boundary: it proves the broker verified both Keycloak-issued JWT signatures, enforced the `token-exchange-broker` audience, resolved the agent from `azp`, and passed CEL authorization — failing only at the user-grant/vault stage. Any earlier misconfiguration (issuer mismatch, wrong audience, unresolved agent) surfaces as a `400`/`401` before this point.

### What is not yet wired: consent + vault

Returning an actual third-party token requires a **user consent grant** for a service with an **active third-party OAuth session** (a vaulted token). The broker enforces this: creating the grant fails with `unconnected services` until the user has completed an OAuth authorization-code flow with the third-party service. KAOS does not currently project consent grants or a real third-party vault (only agent identity + permission sets), so a fully green exchange needs the consent-based delegated-access workflow — tracked as a followup, not part of this posture.

**Proves:** the `aib-keycloak` token-exchange integration end-to-end through Keycloak JWT verification, audience enforcement, agent resolution, and authorization — up to the consent/vault boundary.

## Clean up

```bash
kubectl delete namespace "$APP_NS"
```

## Where to go next

- [`kaos-internal` walkthrough](./walkthrough-kaos) — the self-contained posture with no external IdP or broker.
- [Security Overview](/security/overview) — the layered model and install postures.
- [Authorization](/security/authorization) — providers, modes, verification, and the policy-data schema.
