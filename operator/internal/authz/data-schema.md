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
- Automated resource ids use `kaos://<slug>/<namespace>/<name>`, where `slug` is `agent`, `mcpserver`, `modelapi`, or `memorystore`.

The policy derives the target only from the operator-owned gateway path because external authorization runs before route header modification. Inbound `x-kaos-target-resource` headers are not forwarded to or trusted by the PDP.

## `kaos.jwks`

Maps the exact actor-token issuer to its JSON Web Key Set. The policy selects the issuer entry from the token `iss`, verifies the token with the server-side `RS256` allowlist, and requires the exact issuer plus the `kaos-gateway` audience before trusting its subject.

## `kaos.agents`

Maps logical agent ids to issuer-specific token subjects. ServiceAccount mode uses `system:serviceaccount:<namespace>:<serviceaccount-name>` subjects, so this mapping resolves the verified token subject back to its KAOS actor id.
