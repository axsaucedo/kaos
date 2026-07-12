# KAOS authorization data schema (`data.json`)

The gateway-external OPA policy reads one data document from the policy ConfigMap key `data.json`. Automated projection and administrator-authored manual data use the same published shape.

The shipped policy package is `kaos.authz`, and the Envoy plugin queries its `result` rule at `kaos/authz/result`.

```json
{
  "kaos": {
    "grants": {
      "<actor-id>": ["<resource-id>", "..."]
    },
    "user_grants": {
      "user:<sub-or-email>": ["<resource-id>", "..."],
      "group:<name>": ["<resource-id>", "..."]
    },
    "jwks": {
      "<issuer>": {
        "keys": [ { "kty": "RSA", "kid": "...", "alg": "RS256", "n": "...", "e": "AQAB" } ]
      }
    },
    "agents": {
      "<actor-id>": { "issuer_sub": "<token-subject>", "autonomous": false }
    }
  }
}
```

## `kaos.grants`

Maps an agent's logical actor id to the sorted, deduplicated resources it may reach.

- Actor ids use `kaos://agent/<namespace>/<name>`.
- Automated resource ids use `kaos://<slug>/<namespace>/<name>`, where `slug` is `agent`, `mcpserver`, `modelapi`, or `memorystore`.

The policy derives the target only from the operator-owned gateway path because external authorization runs before route header modification. Inbound `x-kaos-target-resource` headers are not forwarded to or trusted by the PDP.

## `kaos.jwks`

Maps the exact actor-token issuer to its JSON Web Key Set. The policy selects the issuer entry from the token `iss`, verifies the token with the server-side `RS256` allowlist, and requires the exact issuer plus the `kaos-gateway` audience before trusting its subject.

## `kaos.user_grants`

Maps verified user principals to the sorted, deduplicated resources they may enter. Keys use `user:<sub-or-email>` for a token's `sub` or `email`, and `group:<name>` for short names in its `groups` claim. The operator compiles enforced namespaced `AccessGrant` resources into this map.

For example:

```json
{
  "user:alice@example.com": ["kaos://agent/demo/writer"],
  "group:researchers": ["kaos://agent/demo/researcher"]
}
```

User grants gate entry requests. Internal movement is authorized through `kaos.grants` after the propagated subject is verified.

## `kaos.agents`

Maps logical agent ids to issuer-specific token subjects and an `autonomous` boolean. ServiceAccount mode uses `system:serviceaccount:<namespace>:<serviceaccount-name>` subjects, so `issuer_sub` resolves the verified token subject back to its KAOS actor id. `autonomous: true` permits that Agent to use its own verified agent token as the required subject for autonomous execution.

For example:

```json
{
  "kaos://agent/demo/researcher": {
    "issuer_sub": "system:serviceaccount:demo:kaos-agent-researcher",
    "autonomous": true
  }
}
```
