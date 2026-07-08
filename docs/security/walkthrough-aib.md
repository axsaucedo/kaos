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
- The AIB broker Helm chart and a values file available locally (the chart ships a dev preset — see the note on token exchange below).
- On KIND, the operator, agent, and broker images loaded into the cluster (`kind load docker-image ...`).

::: tip NetworkPolicy enforcement
As with `kaos-internal`, the generated `NetworkPolicy` objects are only *enforced* by a NetworkPolicy-capable CNI (for example Calico). The default KIND CNI (kindnet) creates them without enforcing them, which is fine for exploring authorization and routing.
:::

## Step 1 — Install with the `aib-keycloak` preset

Install KAOS with the default `aib-keycloak` preset, pointing at the broker chart and values. The CLI installs the operator, the AIB broker (into `aib-system`), and Keycloak (into `keycloak`, bootstrapping the `kaos` realm):

```bash
kaos system install \
  --namespace kaos-system \
  --auth-enabled aib-keycloak \
  --gateway-enabled --metallb-enabled \
  --aib-chart-path <path-to>/charts/agentic-identity-broker \
  --aib-values <path-to>/charts/agentic-identity-broker/values-dev.yaml \
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
kubectl get configmap kaos-operator-config -n kaos-system -o json \
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
kubectl get pods -n aib-system      # AIB broker (+ ext_proc sidecar)
kubectl get pods -n keycloak        # Keycloak
kubectl get pods -n kaos-system     # operator
```

Confirm the Keycloak realm was bootstrapped:

```bash
kubectl logs -n keycloak deploy/keycloak | grep -i "realm 'kaos'"
```

**Proves:** the broker (agent identity + authorization) and Keycloak (user identity) are both live and the `kaos` realm exists.

## Step 3 — Deploy resources and confirm broker credential minting

Deploy a small topology, then confirm the operator registered each agent with the broker and minted a per-agent credential Secret:

```bash
kubectl create namespace kaos-walkthrough
kubectl apply -n kaos-walkthrough -f \
  https://raw.githubusercontent.com/axsaucedo/kaos/main/operator/config/samples/2-multi-agent-mcp.yaml
```

Unlike `kaos-internal` (where the agent token is header-trusted), each agent here is issued a real broker credential. Inspect the minted Secret:

```bash
kubectl get secret -n kaos-walkthrough -l kaos.tools/managed-by=kaos \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
kubectl get secret kaos-aib-coordinator -n kaos-walkthrough \
  -o jsonpath='{.data.AGENT_AUTH_CLIENT_ID}' | base64 -d; echo
```

The `AGENT_AUTH_CLIENT_ID` / `AGENT_AUTH_CLIENT_SECRET` are populated (broker-issued), not empty. The agent runtime uses them to mint a signed actor-token JWT via OAuth2 `client_credentials` against the broker.

**Proves:** agent identity is broker-backed and cryptographically real, not self-asserted.

## Step 4 — Mint a user token from Keycloak

User identity flows from Keycloak. Port-forward Keycloak and request a subject token with the OIDC password grant:

```bash
kubectl port-forward -n keycloak svc/keycloak 8080:8080 &
curl -s -X POST http://localhost:8080/realms/kaos/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=kaos&username=<realm-user>&password=<password>" \
  | jq -r .access_token
```

This subject token is what a user presents to KAOS. At the gateway it is validated by the `jwt_authn` provider against the Keycloak JWKS before any authorization runs.

**Proves:** user identity is issued and verified against Keycloak, on the same trust root as the rest of the posture.

## Step 5 — Confirm gateway-routed identity and enforcement objects

As with `kaos-internal`, agents reach other resources through the gateway, and the operator generates the enforcement objects:

```bash
kubectl get deploy agent-coordinator -n kaos-walkthrough -o json \
  | jq -r '.spec.template.spec.containers[0].env[]
      | select(.name | test("URL|AGENT_AUTH_IDENTITY"))
      | "\(.name)=\(.value)"'

kubectl get securitypolicy,networkpolicy -n kaos-walkthrough
```

Every outbound URL routes through the gateway path (the `ext_proc` enforcement point cannot be bypassed), and `AGENT_AUTH_IDENTITY` is the single logical identity that threads the whole system — the actor-token `sub`, the broker agent identity, and the authorization subject.

**Proves:** internal calls are gateway-routed and the `ext_proc` authorization hook plus bypass-prevention NetworkPolicies are in place.

## Token exchange (RFC 8693) and current status

The `aib-keycloak` posture is designed to run the RFC 8693 **token-exchange** path in the broker's `ext_proc` sidecar: for a user-present request, the sidecar exchanges the user subject token for the agent's `granted_permission_sets` (and, for third-party APIs, a vaulted upstream OAuth token) before the OPA policy decides allow/deny.

::: warning Token-exchange sidecar prerequisites
The `ext_proc` token-exchange sidecar performs an OAuth2 `client_credentials` grant against the broker **at startup** to mint its own client assertion. This requires:

1. The broker running in **federated** or **hybrid** OAuth2 mode. The chart's `values-dev.yaml` dev preset runs in `local` mode, which mints enduser tokens in-memory and **does not accept the `client_credentials` grant** — so the token-exchange sidecar cannot bootstrap against the dev preset.
2. A bootstrapped OAuth client for the sidecar: an agent registered with the broker admin API, a credential minted via `POST /api/agents/{agent-id}/client-credentials`, and the sidecar configured with the agent's **UUID** as its `client_id` (the broker resolves opaque `client_id` values as agent UUIDs, not display names) plus the minted secret.

Automating this bootstrap end-to-end (federated broker mode wired to Keycloak, plus sidecar credential provisioning) is the remaining work for a fully self-serve token-exchange install. Until then, deploy the broker in `local` mode for identity + agent-credential minting and provision the token-exchange sidecar's OAuth client out of band, or run the broker in federated mode against Keycloak.
:::

**Proves / documents:** the intended enforcement flow and the exact bootstrap prerequisites the token-exchange sidecar needs — captured so the posture can be completed without rediscovering them.

## Clean up

```bash
kubectl delete namespace kaos-walkthrough
```

## Where to go next

- [`kaos-internal` walkthrough](./walkthrough-kaos) — the self-contained posture with no external IdP or broker.
- [Security Overview](/security/overview) — the layered model and install postures.
- [Authorization](/security/authorization) — providers, modes, verification, and the policy-data schema.
