# Security Overview

KAOS secures agent-to-agent and agent-to-tool traffic at the Envoy Gateway. Every call an agent makes to another KAOS resource can be authenticated, authorized, and confined to the gateway path, so a request is checked before it reaches the target workload. Each layer is independent and opt-in, and they compose into a full end-to-end posture.

## Layers

- **Identity** — each agent is issued a signed actor token (`sub = kaos://agent/<namespace>/<name>`) and each user authenticates against an identity provider. The gateway carries the user (subject) token in `Authorization` and the agent (actor) token in `x-agent-authorization`.
- **Authorization** — an Open Policy Agent policy inside the Envoy `ext_proc` filter decides whether an actor may reach a resource. Grant data is either projected by KAOS from your CRDs (`kaos` provider) or owned by an external identity broker (`aib` provider). See [Authorization](/security/authorization).
- **Gateway-only traffic** — NetworkPolicies deny direct workload-to-workload traffic and internal calls are routed through the gateway, so the enforcement point cannot be bypassed. This can be enabled on its own as a defence-in-depth posture. See [Gateway API](/operator/gateway-api#strict-gateway-only-traffic).
- **Transport security** — the gateway can terminate HTTPS (self-signed, cert-manager, or a provided certificate).

## Install postures

The `kaos system install` command bundles these layers into three curated postures selected with `--auth-enabled`:

| Preset | Identity | Authorization | Agent token | Use when |
|--------|----------|---------------|-------------|----------|
| `kaos-internal` | none | KAOS-projected grants (`kaos` provider) | header-trusted (spoofable) | Exploring authorization without an IdP |
| `aib-only` | identity broker | broker permission sets (`aib` provider) | signature-verified against IdP JWKS | Broker-issued agent identity without user login |
| `aib-keycloak` (default) | Keycloak + identity broker | broker permission sets (`aib` provider) | signature-verified against IdP JWKS | Production-like end-to-end security with user auth + token exchange |

```bash
# Self-contained demo — no external identity provider or broker
kaos system install --gateway-enabled --auth-enabled kaos-internal

# Broker-issued agent identity, no user login or token exchange
kaos system install --gateway-enabled --auth-enabled aib-only

# Full verified path — Keycloak user identity + identity broker + token exchange
kaos system install --gateway-enabled --auth-enabled aib-keycloak
```

All presets imply `--gateway-enabled`, route internal traffic through the gateway, and generate bypass-prevention NetworkPolicies. Every underlying knob remains configurable via Helm `--set` for advanced compositions; see [Authorization](/security/authorization#advanced-configuration).

## Enforcement model

Authorization runs as OPA embedded in the gateway `ext_proc` filter. On each request the policy sees the subject identity (from `Authorization`), the actor identity (from `x-agent-authorization`), the target resource (from `x-kaos-target-resource`), and the grant facts — whether KAOS-owned (`data.kaos.grants`) or broker-owned (`granted_permission_sets`). Because the actor token is always present, KAOS-owned authorization also enforces in autonomous mode.

::: warning
OPA only evaluates when a subject bearer token is present. Pure-autonomous agent-to-resource calls with no user token bypass the policy. Use the verified posture and require a token on protected paths for production.
:::

## Gateway-only strict traffic

Strict gateway-only traffic can be enabled independently of authorization to make the gateway the single application path between workloads:

```bash
kaos system install --gateway-enabled --gateway-api-strict
```

Enforcement of the generated NetworkPolicies requires a CNI that implements NetworkPolicy (for example Calico); the default KIND CNI does not. See [Gateway API](/operator/gateway-api#strict-gateway-only-traffic).
