# Walkthrough: AIB identity and Keycloak user authentication

The AIB presets use the Agentic Identity Broker as the agent OAuth issuer. AIB registers agent identities and mints per-agent client credentials; the gateway-external OPA PDP remains the authorization decision point.

## Choose a preset

| Preset | Agent identity | User identity | Policy enforcement |
|---|---|---|---|
| `aib-only` | AIB | none | In-chart OPA |
| `aib-keycloak` | AIB | Keycloak JWT provider | In-chart OPA |

Both presets enable automated policy projection and fail-closed external authorization. `aib-keycloak` additionally installs Keycloak and configures the gateway's user JWT provider.

## Install

The AIB chart is supplied as a local development path:

```bash
export AIB_CHART=../agentic-identity-broker/chart

kaos system install \
  --namespace kaos-system \
  --auth-enabled aib-keycloak \
  --aib-chart-path "$AIB_CHART" \
  --metallb-enabled \
  --wait
```

For agent identity without Keycloak:

```bash
kaos system install \
  --namespace kaos-system \
  --auth-enabled aib-only \
  --aib-chart-path "$AIB_CHART" \
  --wait
```

## Single issuer value

The AIB issuer URL is one value shared by the issuer and all verifiers. The CLI uses it for:

- AIB `server.enduser.publicUrl`, which becomes the actor token `iss`.
- `security.agentAuth.issuer` in the operator configuration.
- The projected `data.kaos.jwks` issuer key.
- The gateway agent JWT provider's `issuer` and JWKS endpoint.

Inspect it with:

```bash
kubectl get configmap kaos-operator-config -n kaos-system \
  -o jsonpath='{.data.SECURITY_AGENT_AUTH_ISSUER}{"\n"}'
```

The operator checks AIB discovery against this value. An issuer mismatch is logged clearly and marks the projection degraded.

## Agent credentials

Deploy a topology:

```bash
kubectl create namespace kaos-walkthrough
kubectl apply -n kaos-walkthrough -f \
  https://raw.githubusercontent.com/axsaucedo/kaos/main/operator/config/samples/2-multi-agent-mcp.yaml
```

The operator registers each Agent with AIB and creates its credential Secret:

```bash
kubectl get secret -n kaos-walkthrough -l app.kubernetes.io/managed-by=kaos-operator-authz
kubectl get deploy agent-coordinator -n kaos-walkthrough -o json \
  | jq '.spec.template.spec.containers[0].env | map(select(.name | startswith("AGENT_AUTH_")))'
```

The runtime uses `AGENT_AUTH_CLIENT_ID`, `AGENT_AUTH_CLIENT_SECRET`, and the configured token endpoint to obtain an actor JWT with OAuth `client_credentials`. AIB does not receive resource grants and does not participate in authorization decisions.

## PDP and policy projection

```bash
kubectl get deploy,service,pdb kaos-pdp -n kaos-system
kubectl get configmap kaos-authz-policy -n kaos-system -o jsonpath='{.data.data\.json}' | jq
kubectl get securitypolicy -n kaos-walkthrough
```

The policy document contains CRD-derived `kaos.grants` and AIB issuer keys in `kaos.jwks`. Envoy verifies the AIB actor JWT, then OPA resolves its `sub` and checks the actor → resource edge.

## Keycloak user JWTs

With `aib-keycloak`, the operator also generates a user JWT provider using the Keycloak issuer and audience. Requests may carry:

```http
Authorization: Bearer <keycloak-user-jwt>
x-agent-authorization: Bearer <aib-agent-jwt>
```

The gateway verifies both configured token types. OPA currently makes its resource decision from the agent actor and target resource; it does not evaluate user → resource grants.

## Operational bounds

- Policy updates and revocations can take about 90 seconds to propagate.
- AIB issuer discovery must return the exact configured issuer.
- The PDP is fail-closed and denies requests while unavailable.

## Clean up

```bash
kubectl delete namespace kaos-walkthrough
```
