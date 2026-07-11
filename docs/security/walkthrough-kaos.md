# Walkthrough: `kaos-internal`

The `kaos-internal` preset provides cluster-issued agent identity and enforced agent → resource authorization with no external identity components.

## Install

```bash
kaos system install \
  --namespace kaos-system \
  --auth-enabled kaos-internal \
  --metallb-enabled \
  --wait
```

The preset enables Envoy Gateway, the in-chart OPA PDP, ServiceAccount identity, automated policy projection, gateway routing, and NetworkPolicy generation.

Verify the control-plane components:

```bash
kubectl get deploy,service,pdb -n kaos-system -l app.kubernetes.io/component=pdp
kubectl get configmap kaos-operator-config -n kaos-system -o json \
  | jq -r '.data | to_entries[] | select(.key | test("SECURITY|AUTHZ|GATEWAY")) | "\(.key)=\(.value)"'
```

Relevant values include:

```text
SECURITY_AGENT_AUTH_IDENTITY_PROVIDER=serviceaccount
SECURITY_PDP_ENABLED=true
SECURITY_AGENT_AUTH_EXT_AUTHZ_URL=kaos-pdp.kaos-system.svc:9191
SECURITY_AUTHORIZATION_POLICY_DATA_SOURCE=automated
AUTHZ_POLICY_CONFIGMAP_NAME=kaos-authz-policy
AUTHZ_POLICY_CONFIGMAP_NAMESPACE=kaos-system
```

## Deploy a topology

```bash
kubectl create namespace kaos-walkthrough
kubectl apply -n kaos-walkthrough -f \
  https://raw.githubusercontent.com/axsaucedo/kaos/main/operator/config/samples/2-multi-agent-mcp.yaml
kubectl get agents,mcpservers,modelapis -n kaos-walkthrough
```

Each Agent receives an owned ServiceAccount and projected token:

```bash
kubectl get serviceaccounts -n kaos-walkthrough
kubectl get deploy agent-coordinator -n kaos-walkthrough -o json \
  | jq '{serviceAccount: .spec.template.spec.serviceAccountName, volumes: .spec.template.spec.volumes, env: .spec.template.spec.containers[0].env}'
```

`AGENT_AUTH_TOKEN_FILE` points to `/var/run/secrets/kaos-agent/token`. Kubelet rotates the audience-restricted token, and the runtime reads the file for each use.

## Inspect policy data

```bash
kubectl get configmap kaos-authz-policy -n kaos-system \
  -o jsonpath='{.data.data\.json}' | jq
```

The document contains:

- `kaos.grants`, derived from the Agents' model, MCP server, and agent-network references.
- `kaos.jwks`, keyed by the Kubernetes issuer discovered through the API server.
- `kaos.agents`, mapping each logical agent id to its `system:serviceaccount:...` subject.

The same ConfigMap contains `policy.rego`. OPA watches both mounted files and applies data updates without restarting the PDP.

## Inspect enforcement objects

```bash
kubectl get httproute,securitypolicy,networkpolicy -n kaos-walkthrough
kubectl get referencegrant -n kaos-system
```

Each `SecurityPolicy` verifies the actor token and calls the `kaos-pdp` gRPC Service with `failOpen: false`. The ReferenceGrant permits workload-namespace policies to reference the PDP Service in `kaos-system`.

## Exercise allow and deny

Mint a token for an Agent ServiceAccount and send it through the gateway:

```bash
TOKEN=$(kubectl create token kaos-agent-coordinator -n kaos-walkthrough --audience=kaos-gateway --duration=10m)
GW_SERVICE=$(kubectl get service -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=kaos-gateway -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward -n envoy-gateway-system service/$GW_SERVICE 18000:80
```

In another shell, call a resource granted to the coordinator:

```bash
curl -i -H "x-agent-authorization: Bearer $TOKEN" \
  http://127.0.0.1:18000/kaos-walkthrough/modelapi/multi-modelapi/health/liveliness
```

A granted edge returns the workload response. A valid token for an Agent without that edge returns 403. A request without `x-agent-authorization` also returns 403. If `kaos-pdp` has no ready endpoints, `failOpen: false` keeps the request denied.

Allow changes and revocations can take about 90 seconds to propagate through projection, the ConfigMap volume, OPA, and gateway configuration.

## Clean up

```bash
kubectl delete namespace kaos-walkthrough
```
