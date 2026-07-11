# Backend-neutral OPA drop-in for KAOS ext_authz

KAOS resource-level authorization is enforced at the Envoy gateway through an `ext_authz` gRPC backend. By default that backend is the AIB access-check service, but the integration is **backend-neutral**: the gateway speaks the standard `envoy.service.auth.v3.Authorization/Check` contract and passes the resource and action as neutral Envoy context extensions (`kaos.resource` / `kaos.action`) plus the gateway-validated actor token. Any backend that implements the same contract — for example [OPA via opa-envoy](https://www.openpolicyagent.org/docs/latest/envoy-introduction/) — can be dropped in **with configuration only**, without any Envoy or KAOS code change.

This sample demonstrates that swap.

## Files

| File | Purpose |
| --- | --- |
| `kaos_authz.rego` | Rego policy deciding `allow`/`deny` from `kaos.resource` / `kaos.action` + the actor token `sub`, mirroring AIB permission-set coverage. |
| `kaos_grants.json` | Grant data bundle (actor → granted resources/actions). In production this is sourced from the same grants the broker projects. |
| `opa-envoy.yaml` | `opa-system` namespace, a ConfigMap with the policy + data, and an `opa-envoy` Deployment/Service exposing the ext_authz gRPC plugin on `:9191`. |

## How the swap works (configuration only)

The operator generates the `SecurityPolicy.spec.extAuth.grpc.backendRef` from a single configuration value — the ext_authz backend host:port. Pointing it at opa-envoy instead of AIB is a config change:

```bash
# CLI — select an auth preset and override the ext_authz backend
kaos system install --auth-enabled aib-keycloak \
  --set security.agentAuth.extAuthzUrl=opa-envoy.opa-system.svc.cluster.local:9191

# or Helm
helm upgrade kaos kaos/kaos-operator \
  --set security.agentAuth.extAuthzUrl=opa-envoy.opa-system.svc.cluster.local:9191
```

No Envoy configuration, generated-policy shape, or KAOS code changes — only the backend reference. This is locked by `TestConstructSecurityPolicyBackendRefIsConfigDriven` in `operator/pkg/security/securitypolicy_test.go`, which asserts the generated `extAuth.grpc.backendRef` follows the configured URL for both the default AIB backend and the opa-envoy backend.

## Validate in KIND

```bash
# 1. Deploy the opa-envoy ext_authz backend.
kubectl apply -f docs/security/opa-drop-in/opa-envoy.yaml
kubectl -n opa-system rollout status deploy/opa-envoy

# 2. Point KAOS at it (config only) and enable auth.
kaos system install --auth-enabled aib-keycloak \
  --set security.agentAuth.extAuthzUrl=opa-envoy.opa-system.svc.cluster.local:9191 --wait

# 3. A granted edge is allowed, an ungranted one is denied — equivalently to AIB.
#    (agent `demo/researcher` is granted `call` on `mcpserver/demo/github` only.)
```

A request whose actor/resource/action matches a grant in `kaos_grants.json` returns an Envoy `OkHttpResponse`; anything else is denied — the same allow/deny outcome the AIB access-check produces, proving the contract is backend-neutral.

AIB remains the default authorization backend; OPA is a validated optional drop-in only.
