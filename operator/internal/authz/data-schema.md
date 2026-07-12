# KAOS authorization data schema (`data.json`)

The gateway-external OPA policy reads one data document from the policy ConfigMap key `data.json`. Automated projection and administrator-authored manual data use the same published shape.

```json
{
  "kaos": {
    "grants": {
      "<actor-id>": ["<resource-id>", "..."]
    },
    "jwks": {
      "<issuer>": {
        "keys": [ { "kty": "RSA", "kid": "...", "alg": "RS256", "n": "...", "e": "AQAB" } ]
      }
    },
    "agents": {
      "<actor-id>": { "issuer_sub": "<token-subject>" }
    }
  }
}
```

## `kaos.grants`

Maps an agent's logical actor id to the sorted, deduplicated resources it may reach.

- Actor ids use `kaos://agent/<namespace>/<name>`.
- Automated resource ids use `kaos://<slug>/<namespace>/<name>`, where `slug` is `agent`, `mcpserver`, or `modelapi`. Manual policy data can also address a protected MemoryStore route with the `memorystore` slug.

The policy derives the target only from the operator-owned gateway path because external authorization runs before route header modification. Inbound `x-kaos-target-resource` headers are not forwarded to or trusted by the PDP.

## `kaos.jwks`

Maps the exact actor-token issuer to its JSON Web Key Set. The policy selects the issuer entry from the token `iss` and verifies the token before trusting its subject. ServiceAccount tokens also require the `kaos-gateway` audience.

## `kaos.agents`

Maps logical agent ids to issuer-specific token subjects. ServiceAccount mode uses `system:serviceaccount:<namespace>:<serviceaccount-name>` subjects, so this mapping resolves the verified token subject back to its KAOS actor id.
