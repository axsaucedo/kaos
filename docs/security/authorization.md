# Authorization

KAOS enforces agent authorization at the gateway: every request an agent makes to another KAOS resource (an MCP server, a model API, or another agent) can be checked before it is forwarded. Enforcement runs as an Open Policy Agent (OPA) policy inside the Envoy `ext_proc` filter, so a denied request never reaches the target workload.

Authorization is optional and off by default. You turn it on at install time and pick who authors the policy data.

## Concepts

- **Actor identity** — the agent making the call. It is the `sub` claim of the agent (actor) token carried in the `x-agent-authorization` header, and equals the agent logical identity `kaos://agent/<namespace>/<name>`.
- **Resource identity** — the target being called. It is the logical identity `kaos://<slug>/<namespace>/<name>` (`slug` is `mcpserver`, `modelapi`, or `agent`), matched against the `x-kaos-target-resource` header the gateway stamps onto the request.
- **Grant** — a decision fact stating that an actor may reach a resource. Grants live in `data.kaos.grants`, a published contract (see [Policy data schema](#policy-data-schema)).
- **Provider** — who owns the authorization decision data: `kaos` (KAOS projects grants from your CRDs) or `aib` (an external identity broker owns permission sets).

## Providers

### `kaos` — KAOS-owned policy data

The operator derives the grant graph from your `Agent`, `MCPServer`, and `ModelAPI` resources (their `mcpServers`, `agentNetwork.access`, and model references) and writes it, together with a static policy, into a single policy ConfigMap that the enforcement engine mounts. No external broker is required. This is the recommended starting point and works in autonomous mode because the actor token is always present.

### `aib` — broker permission sets

The operator registers agents with an external identity broker and enforcement reads the broker's `granted_permission_sets` returned from token exchange. Use this when the broker is your source of truth for authorization.

## Modes

Select a mode with `kaos system install` flags. All modes are safe by construction: KAOS never overwrites or prunes policy data that it does not own.

| Mode | Provider | `--policy-data-source` | KAOS writes | Use when |
|------|----------|------------------------|-------------|----------|
| Automated (default) | `kaos` | `automated` | `policy.rego` + `data.json` grants | KAOS should project grants from CRDs |
| Bring-your-own ConfigMap | `kaos` | `manual` | nothing | You author both the rego and the data in your own ConfigMap |
| Operator-rego + admin data | `kaos` | `manual` (with `--policy-rego-override`) | `policy.rego` only | KAOS owns the policy, you author `data.kaos.grants` |
| Broker external off-switch | `aib` | `external` | identity only (no grants, no prune) | The broker owns authorization; KAOS only registers identity |

### Automated (default)

KAOS projects grants from your resources and keeps them in sync as agents are added or removed.

```bash
kaos system install \
  --auth-enabled \
  --authz-provider kaos \
  --policy-data-source automated \
  --agent-jwt-verification verified \
  --policy-configmap-name kaos-authz-policy \
  --policy-configmap-namespace kaos-system
```

### Bring-your-own ConfigMap

KAOS points the enforcement engine at a ConfigMap you fully own and never modifies it. Author both `policy.rego` and `data.json` yourself.

```bash
kaos system install \
  --auth-enabled \
  --authz-provider kaos \
  --policy-data-source manual \
  --policy-configmap-name my-policy \
  --policy-configmap-namespace kaos-system
```

### Operator-rego + admin data

KAOS owns only the `policy.rego` key (via server-side-apply field ownership) and never writes `data.kaos.grants`, so you can author grants directly while still getting policy updates from KAOS.

```bash
kaos system install \
  --auth-enabled \
  --authz-provider kaos \
  --policy-data-source manual \
  --policy-rego-override \
  --policy-configmap-name kaos-authz-policy \
  --policy-configmap-namespace kaos-system
```

### Broker external off-switch

KAOS keeps registering agent identities and minting per-agent credential Secrets, but disables authorization projection and forces prune off. The broker is authoritative; enforcement reads it live.

```bash
kaos system install \
  --auth-enabled \
  --authz-provider aib \
  --policy-data-source external \
  --admin-url http://aib.aib-system:8000/api
```

## Verification modes

The subject (user) token is always verified by the gateway's JWT authentication. The actor token needs the same treatment for a production posture, controlled by `--agent-jwt-verification`:

- `verified` — the operator injects the IdP JWKS at `data.kaos.jwks` and the policy verifies the actor token signature, issuer, and expiry before trusting its `sub`. This is the real posture.
- `skip` — **demo mode, non-production.** The policy decodes the actor token without verifying its signature, so the `x-agent-authorization` header is spoofable. Use it only to try route- and agent-level authorization without an identity provider. Move to `verified` before any real deployment.

::: warning
Demo mode (`--agent-jwt-verification skip`) trusts an unverified header and is spoofable. It exists to explore authorization without an IdP and must never be used in production.
:::

## Policy data schema

The enforcement policy reads one OPA data document from the policy ConfigMap key `data.json`. This shape is a published contract: the operator projects it in automated mode, and you author it directly in operator-rego and bring-your-own modes.

```json
{
  "kaos": {
    "grants": {
      "kaos://agent/<namespace>/<name>": [
        "kaos://mcpserver/<namespace>/<name>",
        "kaos://agent/<namespace>/<name>"
      ]
    },
    "jwks": {
      "keys": [ { "kty": "RSA", "kid": "...", "n": "...", "e": "AQAB" } ]
    }
  }
}
```

### `kaos.grants` (required)

Maps an actor identity to the sorted, de-duplicated set of resource identities it may reach. A request is allowed only when its resource id is present in the granting array for its actor id.

- **Actor id** — `kaos://agent/<namespace>/<name>`, the `sub` of the agent token in `x-agent-authorization`.
- **Resource id** — `kaos://<slug>/<namespace>/<name>` (`slug` is `mcpserver`, `modelapi`, or `agent`), matched against the `x-kaos-target-resource` header.

### `kaos.jwks` (optional)

The IdP JSON Web Key Set used to verify the actor token signature. Its presence switches the policy from demo mode (decode only) to verified mode (`io.jwt.decode_verify` against these keys). Omit it only in demo installs.
