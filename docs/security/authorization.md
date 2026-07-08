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

## Installing

The `kaos system install` command exposes two curated end-to-end postures through the single `--full-auth-enabled` flag. Both enable OPA-in-`ext_proc` authorization, route internal traffic through the gateway, and generate bypass-prevention NetworkPolicies.

### Demo posture (no identity provider)

`kaos-internal-demo` uses the `kaos` provider with grants projected from your CRDs and the agent token header-trusted, so you can explore route- and agent-level authorization without Keycloak or a broker.

```bash
kaos system install --gateway-enabled --full-auth-enabled kaos-internal-demo
```

### Full verified posture

`keycloak-aib-enabled` (the default when `--full-auth-enabled` is passed without a value) installs Keycloak for user identity and wires the identity broker with RFC 8693 token exchange. Authorization reads the broker's permission sets and the agent token signature is verified against the IdP JWKS.

```bash
kaos system install --gateway-enabled --full-auth-enabled keycloak-aib-enabled
```

### Advanced configuration

The presets cover the common cases. Every underlying knob remains available as a Helm chart value via `--set`, so you can compose any of the modes below. All modes are safe by construction: KAOS never overwrites or prunes policy data that it does not own.

| Mode | Provider | `policyDataSource` | KAOS writes | Use when |
|------|----------|--------------------|-------------|----------|
| Automated (default) | `kaos` | `automated` | `policy.rego` + `data.json` grants | KAOS should project grants from CRDs |
| Bring-your-own ConfigMap | `kaos` | `manual` | nothing | You author both the rego and the data in your own ConfigMap |
| Operator-rego + admin data | `kaos` | `manual` (+ `policyRegoOverride`) | `policy.rego` only | KAOS owns the policy, you author `data.kaos.grants` |
| Broker external off-switch | `aib` | `external` | identity only (no grants, no prune) | The broker owns authorization; KAOS only registers identity |

The relevant chart values are:

```bash
kaos system install --gateway-enabled --full-auth-enabled kaos-internal-demo \
  --set security.agentAuth.authorization.provider=kaos \
  --set security.agentAuth.authorization.policyDataSource=manual \
  --set security.agentAuth.authorization.policyRegoOverride=true \
  --set security.agentAuth.authorization.agentJwtVerification=verified \
  --set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
  --set security.agentAuth.projection.policyConfigMap.namespace=kaos-system
```

## Verification modes

The subject (user) token is always verified by the gateway's JWT authentication. The actor token needs the same treatment for a production posture, controlled by `security.agentAuth.authorization.agentJwtVerification` (the `keycloak-aib-enabled` preset sets `verified`; `kaos-internal-demo` sets `skip`):

- `verified` — the operator injects the IdP JWKS at `data.kaos.jwks` and the policy verifies the actor token signature, issuer, and expiry before trusting its `sub`. This is the real posture.
- `skip` — **demo mode, non-production.** The policy decodes the actor token without verifying its signature, so the `x-agent-authorization` header is spoofable. Use it only to try route- and agent-level authorization without an identity provider. Move to `verified` before any real deployment.

::: warning
Demo mode (`agentJwtVerification=skip`, the `kaos-internal-demo` preset) trusts an unverified header and is spoofable. It exists to explore authorization without an IdP and must never be used in production.
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
