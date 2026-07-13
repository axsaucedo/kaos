# Authorization

KAOS requires a verified user or autonomous-Agent subject on every hop. User `AccessGrant`s gate entry, Agent grants gate internal movement, and a gateway-external OPA deployment evaluates every protected request through Envoy's gRPC external-authorization filter.

## Enforcement components

When `security.pdp.enabled=true`:

1. The chart deploys `kaos-pdp` with two replicas, a gRPC Service on port 9191, and a PodDisruptionBudget with `minAvailable: 1`.
2. The operator attaches a `SecurityPolicy` to every internal Agent, MCPServer, ModelAPI, and MemoryStore route.
3. The gateway verifies recognized JWTs and sends the subject and actor credentials to OPA.
4. OPA evaluates `data.kaos.authz.result` using the mounted `policy.rego` and `data.json` files.
5. Envoy forwards allowed requests and returns 403 for policy denials. `failOpen: false` also denies requests when the PDP cannot answer.

The policy ConfigMap must be in the PDP's namespace because Kubernetes cannot mount a ConfigMap across namespaces. Helm rejects an incompatible configuration during rendering.

## Identity and request conventions

### Actor token

The calling agent sends its JWT in:

```http
x-agent-authorization: Bearer <actor-jwt>
```

The gateway's agent JWT provider validates the token against the selected issuer and requires audience `kaos-gateway`. ServiceAccount mode uses the discovered Kubernetes issuer and an inline JWKS. AIB mode uses the single configured AIB issuer URL and its JWKS; the broker must mint agent tokens with `kaos-gateway` in their audience claim.

## Delegated third-party token exchange

`kaos system install --token-exchange-enabled` is an optional Keycloak-only posture for agents acting as the requesting user against an external OAuth service. Services, scopes, protected-resource URL prefixes, and Agent permission-set bindings are administered in AIB. Every 45 seconds the operator reads AIB, keeps the bound Agent record keyed by `kaos/<namespace>/<name>` and its Keycloak DCR `client_id` current, generates the required FQDN `Backend` and `HTTPRoute`, and injects re-mint targets only into bound Agents. It attaches AIB ext_proc only to routes carrying its generated-egress label; internal Agent, MCPServer, ModelAPI, and MemoryStore routes can never be selected. Static per-MCP credentials remain the default when the feature is off.

The operator never creates AIB services or permission sets. AIB is the declaration and audit surface; Kubernetes contains only reflected plumbing. Reflection is poll-based and fail-static when AIB is unavailable.

The runtime re-mint is implemented separately. Its contract is an `Authorization: Bearer <token>` header containing a Keycloak token with the original user `sub`, the acting Agent's DCR client id in `azp`, and `token-exchange-broker` in `aud`. The chart orders gateway filters as `jwt_authn`, then the PDP `ext_authz`, then `ext_proc`; ext_proc is fail closed and replaces that header only on the dedicated third-party route.

ServiceAccount token subjects have the form `system:serviceaccount:<namespace>:<serviceaccount-name>`. The policy resolves that issuer subject to the logical actor id through `data.kaos.agents`.

### Resource identity

Resource ids use these forms:

- `kaos://agent/<namespace>/<name>`
- `kaos://mcpserver/<namespace>/<name>`
- `kaos://modelapi/<namespace>/<name>`
- `kaos://memorystore/<namespace>/<name>`

Automated projection emits grants for Agent, MCPServer, and ModelAPI relationships. A manual data document can grant a protected MemoryStore route by using its `kaos://memorystore/...` id.

Operator-owned routes stamp the logical id in `x-kaos-target-resource`. Envoy performs external authorization before applying the HTTPRoute request-header modifier, so the policy also derives the same identity from the route path `/<namespace>/<route-kind>/<name>/...`. The route kind `mcp` maps to the resource slug `mcpserver`.

Clients must not use `x-kaos-target-resource` to select an arbitrary resource. The gateway route and its path are authoritative.

### Subject token

The standard `Authorization: Bearer <subject-jwt>` header carries the required subject. At entry it is a Keycloak user token; autonomous Agents use their own agent token. Internal calls propagate the subject unchanged. The PDP verifies the token and applies `data.kaos.user_grants` at user entry or checks `data.kaos.agents[id].autonomous` for agent self-subjecting.

## Automated and manual policy data

`security.agentAuth.authorization.policyDataSource` accepts:

- `automated`: the operator writes the shipped policy and derives `data.json` from Agent relationships and referenced resources.
- `manual`: an administrator owns the ConfigMap data. With `policyRegoOverride=true`, the operator owns only `policy.rego` while the administrator owns `data.json`.

The PDP runs whenever its policy ConfigMap is configured; there is no authorization-provider selector.

## Published `data.kaos` schema

OPA reads this document from the ConfigMap key `data.json`:

```json
{
  "kaos": {
    "grants": {
      "kaos://agent/demo/researcher": [
        "kaos://mcpserver/demo/github",
        "kaos://modelapi/demo/llama"
      ]
    },
    "user_grants": {
      "group:researchers": [
        "kaos://agent/demo/researcher"
      ]
    },
    "jwks": {
      "https://kubernetes.default.svc.cluster.local": {
        "keys": [
          { "kty": "RSA", "kid": "key-id", "alg": "RS256", "n": "...", "e": "AQAB" }
        ]
      }
    },
    "agents": {
      "kaos://agent/demo/researcher": {
        "issuer_sub": "system:serviceaccount:demo:kaos-agent-researcher",
        "autonomous": false
      }
    }
  }
}
```

### `data.kaos.grants`

Maps each logical agent id to a sorted, deduplicated list of resources it may reach. A request is allowed only when the resolved actor id has the target resource in this list.

### `data.kaos.jwks`

Maps the exact token issuer string to its JSON Web Key Set. The policy selects keys by the unverified token's `iss`, then verifies the signature with the server-side `RS256` allowlist and requires the exact issuer plus the `kaos-gateway` audience for every configured issuer.

### `data.kaos.user_grants`

Maps `user:<sub-or-email>` and `group:<short-name>` principals to the resources they may enter. The operator compiles enforced namespaced `AccessGrant` resources into this map.

### `data.kaos.agents`

Maps a logical agent id to its issuer-specific token subject and `autonomous` boolean. ServiceAccount mode uses the reverse lookup because Kubernetes subjects are not KAOS resource ids. The autonomous flag controls whether the Agent may use its own token as the required subject.

## Configuration example

```bash
kaos system install --agent-auth-enabled service-account --user-auth-enabled none \
  --set security.agentAuth.authorization.policyDataSource=automated \
  --set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
  --set security.agentAuth.projection.policyConfigMap.namespace=kaos-system \
  --wait
```

Set `security.agentAuth.extAuthzUrl` only to replace the in-chart PDP Service with another Envoy-compatible gRPC authorizer. The explicit URL takes precedence over `kaos-pdp.<release-namespace>.svc:9191`.

## Propagation and key rotation

Authorization data is eventually consistent. Budget about 90 seconds for resource reconciliation, ConfigMap projection, kubelet volume refresh, OPA file watching, and gateway configuration; this bound also applies to revocations.

ServiceAccount issuer discovery and JWKS loading happen during operator startup. Restart the operator after Kubernetes ServiceAccount signing-key rotation.

See [Authentication and authorization](/security/walkthrough-auth) for the end-to-end gateway and PDP request path.
