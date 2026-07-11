# KAOS authorization data schema (`data.json`)

The enforcement policy (`policy.rego`) reads a single OPA data document from the
policy ConfigMap key `data.json`. This document is a published contract: an admin
authors it directly in the operator-rego mode, and the operator projects it in the
automated mode. Both produce the same shape.

```json
{
  "kaos": {
    "grants": {
      "<actor-id>": ["<resource-id>", "..."]
    },
    "jwks": {
      "<issuer>": {
        "keys": [ { "kty": "RSA", "kid": "...", "n": "...", "e": "AQAB" } ]
      }
    },
    "agents": {
      "<actor-id>": { "issuer_sub": "<token-subject>" }
    }
  }
}
```

## `kaos.grants` (required)

Maps an actor identity to the sorted, de-duplicated set of resource identities it
may reach.

- **Actor id** — the agent logical identity `kaos://agent/<namespace>/<name>`. It
  is the `sub` claim of the agent (actor) token carried in the
  `x-agent-authorization` header.
- **Resource id** — the target logical identity `kaos://<slug>/<namespace>/<name>`
  (`slug` is `mcpserver`, `modelapi`, or `agent`). It is matched against the
  `x-kaos-target-resource` header the gateway stamps onto the request.

A request is allowed only when the request's resource id is present in the
granting array for the request's actor id.

## `kaos.jwks` (optional)

The issuer-keyed IdP JSON Web Key Set used to verify the actor token signature. Its presence
switches the policy from demo mode (decode without verifying, spoofable,
non-production) to verified mode (`io.jwt.decode_verify` against these keys before
trusting the `sub`). Omit it only in demo/non-production installs.

## `kaos.agents` (optional)

Maps logical agent identities to issuer subjects when the token subject is not
the logical KAOS id. ServiceAccount identity uses subjects of the form
`system:serviceaccount:<namespace>:<serviceaccount>`.
