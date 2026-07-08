# End-to-end security walkthrough

This walkthrough stands up KAOS with a full security posture and then verifies, step by step, that agent identity, authorization, and gateway-only routing actually take effect. Every step lists what it proves, and each check can be run from the command line or observed in the KAOS UI.

It uses the self-contained `kaos-internal` preset so the whole flow runs on a local KIND cluster with no external identity provider or broker. The same steps apply to the `aib-only` and `aib-keycloak` postures; the differences are called out where they matter.

## What you will verify

1. The install preset expands into the operator's authorization and routing configuration.
2. The operator projects a policy ConfigMap (`policy.rego` + `data.json`) whose grant graph is derived from your CRDs.
3. Each agent is wired to reach other resources **through the gateway**, and its identity matches the grant graph.
4. `SecurityPolicy` and `NetworkPolicy` objects are generated to keep the gateway on the request path.
5. The projected grants stay stable across reconciles.

## Prerequisites

- A Kubernetes cluster. A local KIND cluster is fine for `kaos-internal`.
- The `kaos` CLI installed (`pip install kaos-cli`).
- `kubectl` pointed at the cluster.

::: tip NetworkPolicy enforcement
The generated `NetworkPolicy` objects are always created, but they are only *enforced* by a CNI that implements NetworkPolicy (for example Calico). The default KIND CNI (kindnet) creates them without enforcing them, which is fine for exploring authorization and routing. Use Calico when you need the isolation to actually block traffic.
:::

## Step 1 — Install with a security preset

Install KAOS with the `kaos-internal` preset. It enables OPA-in-`ext_proc` authorization with the KAOS-owned policy provider, routes internal traffic through the gateway, and generates bypass-prevention NetworkPolicies — all without an external IdP or broker.

```bash
kaos system install \
  --namespace kaos-system \
  --auth-enabled kaos-internal \
  --gateway-enabled \
  --metallb-enabled \
  --wait
```

The three presets differ only in the identity and verification layers:

| Preset | User identity | Agent token | Authorization provider |
|--------|---------------|-------------|------------------------|
| `kaos-internal` | none | header-trusted (spoofable, demo only) | `kaos` (grants projected from CRDs) |
| `aib-only` | none | broker-issued, signature-verified | `aib` (broker permission sets) |
| `aib-keycloak` (default) | Keycloak + token exchange | broker-issued, signature-verified | `aib` (broker permission sets) |

**Proves:** the install command accepts a single preset instead of a large set of auth flags.

### Verify the operator picked up the configuration

The preset is expanded into operator configuration, delivered through the `kaos-operator-config` ConfigMap:

```bash
kubectl get configmap kaos-operator-config -n kaos-system -o json \
  | jq -r '.data | to_entries[] | select(.key | test("SECURITY|AUTHZ|GATEWAY")) | "\(.key)=\(.value)"'
```

Expected keys for `kaos-internal`:

```
SECURITY_AUTHORIZATION_PROVIDER=kaos
SECURITY_AUTHORIZATION_AGENT_JWT_VERIFICATION=skip
SECURITY_AUTHORIZATION_POLICY_DATA_SOURCE=automated
SECURITY_GATEWAY_ROUTING_ENABLED=true
AUTHZ_POLICY_CONFIGMAP_NAME=kaos-authz-policy
AUTHZ_POLICY_CONFIGMAP_NAMESPACE=kaos-system
```

**Proves:** the preset baked in the KAOS authorization provider, the demo (header-trusted) verification mode, and the policy ConfigMap projection target — no extra flags were needed.

## Step 2 — Deploy resources to authorize

Authorization data is derived from your resources, so deploy a small topology: a model API, an MCP tool server, a coordinator agent, and two worker agents the coordinator delegates to.

```bash
kubectl create namespace kaos-walkthrough
kubectl apply -n kaos-walkthrough -f \
  https://raw.githubusercontent.com/axsaucedo/kaos/main/operator/config/samples/2-multi-agent-mcp.yaml
```

Wait for the workloads to come up:

```bash
kubectl get agents,mcpservers,modelapis -n kaos-walkthrough
kubectl get deploy -n kaos-walkthrough
```

**Proves:** the operator reconciles the CRDs into running workloads under the security posture.

::: tip In the UI
Run `kaos ui` and open the namespace. The coordinator, the two workers, the MCP server, and the model API appear as connected resources, showing the delegation and tool topology the grant graph is derived from.
:::

## Step 3 — Inspect the projected policy

Once resources exist, the operator projects the policy ConfigMap the enforcement engine reads:

```bash
kubectl get configmap kaos-authz-policy -n kaos-system \
  -o jsonpath='{.data.data\.json}' | jq
```

Expected grant graph (derived from the sample topology — the coordinator may reach the workers, the MCP server, and the model API; each worker may reach the MCP server and the model API):

```json
{
  "kaos": {
    "grants": {
      "kaos://agent/kaos-walkthrough/coordinator": [
        "kaos://agent/kaos-walkthrough/worker-1",
        "kaos://agent/kaos-walkthrough/worker-2",
        "kaos://mcpserver/kaos-walkthrough/multi-echo-mcp",
        "kaos://modelapi/kaos-walkthrough/multi-modelapi"
      ],
      "kaos://agent/kaos-walkthrough/worker-1": [
        "kaos://mcpserver/kaos-walkthrough/multi-echo-mcp",
        "kaos://modelapi/kaos-walkthrough/multi-modelapi"
      ],
      "kaos://agent/kaos-walkthrough/worker-2": [
        "kaos://mcpserver/kaos-walkthrough/multi-echo-mcp",
        "kaos://modelapi/kaos-walkthrough/multi-modelapi"
      ]
    }
  }
}
```

The ConfigMap also carries a `policy.rego` key — the static policy that decides `allow`/`deny` by looking up the actor identity in `data.kaos.grants` and matching the target resource. The rego is fixed; only the data changes as resources come and go. See the [Policy data schema](/security/authorization#policy-data-schema) for the published contract.

**Proves:** authorization data is projected automatically from the CRD topology, with no hand-authored policy.

## Step 4 — Confirm gateway-routed identity

Inspect a coordinator pod's environment to see how it reaches other resources and how it identifies itself:

```bash
kubectl get deploy agent-coordinator -n kaos-walkthrough -o json \
  | jq -r '.spec.template.spec.containers[0].env[]
      | select(.name | test("URL|AGENT_AUTH_IDENTITY"))
      | "\(.name)=\(.value)"'
```

Expected (addresses point at the gateway, not the target Service directly):

```
MODEL_API_URL=http://<gateway-ip>/kaos-walkthrough/modelapi/multi-modelapi
MCP_SERVER_multi-echo-mcp_URL=http://<gateway-ip>/kaos-walkthrough/mcp/multi-echo-mcp
PEER_AGENT_WORKER_1_CARD_URL=http://<gateway-ip>/kaos-walkthrough/agent/worker-1
AGENT_AUTH_IDENTITY=kaos://agent/kaos-walkthrough/coordinator
```

Two things line up here: every outbound URL routes through the gateway path (so the enforcement point cannot be bypassed), and `AGENT_AUTH_IDENTITY` matches the grant graph key from Step 3 exactly. That single logical identity threads the whole system — it is the actor token `sub`, the OPA data key, and the resource identity.

**Proves:** internal calls are routed through the gateway and the agent's identity is the same key authorization decisions are made against.

## Step 5 — Confirm the enforcement objects

The operator generates the gateway and isolation objects that keep the gateway on the path:

```bash
kubectl get securitypolicy,networkpolicy -n kaos-walkthrough
```

Each MCP server, model API, and agent gets a `SecurityPolicy` (wiring the `ext_proc` authorization hook) and a `NetworkPolicy` (denying direct workload-to-workload traffic so requests must traverse the gateway).

**Proves:** the bypass-prevention layer is generated alongside the workloads.

## Step 6 — Confirm grant stability

Grants should only change when the topology changes, not on every reconcile. Capture the data, force a reconcile, and compare:

```bash
before=$(kubectl get configmap kaos-authz-policy -n kaos-system -o jsonpath='{.data.data\.json}' | shasum)
kubectl annotate agent coordinator -n kaos-walkthrough kaos.tools/rev="$(date +%s)" --overwrite
sleep 8
after=$(kubectl get configmap kaos-authz-policy -n kaos-system -o jsonpath='{.data.data\.json}' | shasum)
[ "$before" = "$after" ] && echo "grants stable" || echo "grants changed"
```

Now change the topology and watch the grants follow it — delete a worker and confirm its grants disappear:

```bash
kubectl delete agent worker-2 -n kaos-walkthrough
sleep 8
kubectl get configmap kaos-authz-policy -n kaos-system -o jsonpath='{.data.data\.json}' | jq '.kaos.grants | keys'
```

The `kaos://agent/kaos-walkthrough/worker-2` key is gone, and it is removed from the coordinator's grants.

**Proves:** projection is idempotent across reconciles and tracks the live topology.

## Verification modes and production posture

`kaos-internal` runs in **demo mode**: the agent token is header-trusted and therefore spoofable. It exists to explore route- and agent-level authorization without an identity provider and must never be used in production.

For a real posture, use `aib-only` or `aib-keycloak`, where the agent token is a broker-issued, signature-verified JWT and the policy verifies its signature, issuer, and expiry against the IdP JWKS before trusting the actor identity. See [Verification modes](/security/authorization#verification-modes).

## Strict gateway-only traffic

Gateway-only isolation can also be enabled independently of authorization as a defence-in-depth posture:

```bash
kaos system install --gateway-enabled --gateway-api-strict
```

This turns on the NetworkPolicy isolation and gateway routing without requiring any auth layer. As noted above, isolation is only enforced by a NetworkPolicy-capable CNI. See [Gateway API](/operator/gateway-api#strict-gateway-only-traffic).

## Clean up

```bash
kubectl delete namespace kaos-walkthrough
```

## Where to go next

- [Security Overview](/security/overview) — the layered model and install postures.
- [Authorization](/security/authorization) — providers, modes, verification, and the policy-data schema.
