# Implementation report — AIB-native delegated third-party access

This branch ships opt-in delegated access to OAuth-protected third-party services through an AIB-native integration. AIB is exchange-only: third-party services, permission sets, and Agent bindings are administered in AIB, not through a KAOS CRD. The operator reflects that AIB state into generated, fail-closed egress plumbing and bound-Agent runtime configuration. The final annotation-free design passed the full consent, exchange, denial, revocation, and internal-route isolation flow on the wire.

The branch originally implemented and validated a `ThirdPartyService` CRD design. That implementation was real, but it was superseded after the 2026-07-13 architecture decision made AIB the single declaration surface. No `ThirdPartyService` CRD remains in the shipped design.

## Model as shipped

- Token exchange is feature-gated and off by default. `kaos system install --token-exchange-enabled --aib-chart-path <chart>` requires Keycloak user and Agent identity and enables Envoy Gateway's Backend extension API for new installations.
- AIB is used only for third-party token exchange, consent, and vaulted provider credentials. It does not issue KAOS Agent identity and does not authorize internal KAOS traffic.
- Administrators create services and permission sets in AIB and bind them to the Agent's stable logical key, `kaos/<namespace>/<name>`. There is no KAOS third-party-service CRD, annotation, or administrator-authored egress route.
- The operator registers or patches the corresponding AIB Agent record and keeps its `client_id` aligned with the Agent's current Keycloak DCR client while preserving AIB-administered permission-set bindings.
- On a 45-second poll, the operator reads AIB Agents, services, and permission sets and generates namespace-local `Backend`, `HTTPRoute`, fail-closed `SecurityPolicy`, and fail-closed `EnvoyExtensionPolicy` resources. The ext_proc policy can target only operator-generated token-exchange routes.
- Only bound Agents receive per-Agent `KAOS_TOKEN_EXCHANGE_CONFIG`, derived from AIB protected resources. Unbound Agents receive no exchange target configuration.
- Session B runtime behavior is unchanged by the AIB-native rework: the runtime re-mints the requesting user's Keycloak token as the acting Agent, preserving the user `sub`, setting `azp` to the Agent DCR client, and emitting only `aud=token-exchange-broker`. AIB ext_proc exchanges that token for the user's vaulted provider token.
- Missing, expired, or revoked consent remains a controlled `third_party_reauth_required` result with an authorization URL. The user completes OAuth and retries. Internal Agent, MCPServer, ModelAPI, and MemoryStore traffic retains the original user token and never traverses ext_proc.

## Implementation arc

| Phase | Outcome | Commits |
|---|---|---|
| Feature gate and initial CRD implementation | Added token-exchange installation, the `ThirdPartyService` CRD, AIB projection, route-scoped ext_proc, per-Agent targets, runtime re-mint, consent handling, and removal reconciliation. This design was built and validated, then superseded. | `d06f5e48`, `d65e7d58`, `d7c6dcd8`, `cef3ea07`, `7a8b6be6`, `e6834292`, `739c739a`, `b5d26657`, `ea6c5e5b`, `36f90089` |
| First live-flow fixes | Fixed AIB chart environment wiring, custom-Agent toolset attachment, re-entrant actor-token minting, delegated-egress PDP handling, and Keycloak/AIB identity setup; aligned the original walkthrough with its passing wire evidence. | `11223b59`–`d7d4acb3` |
| AIB-native rework | Removed the CRD and its samples/controllers, reflected AIB-administered Agents/services/permission sets, generated egress resources, kept Agent DCR identity current by stable key, and isolated projector failures. | `35144981`, `50ba5d04`, `d0c4c594`, `5719e94a`, `b8c14fb8` |
| Install support | Enabled Envoy Gateway's Backend extension API for token-exchange installations and aligned CLI tests/samples with the removed CRD. | `8578e782`, `9d4acee7`, `bc036a6a` |
| Egress hardening | Bound the delegated token's `azp` to the verified actor's projected DCR client and attached the normal fail-closed `SecurityPolicy` to every generated egress route. | `e4636fbb`, `e68e76da`, `34dfce3f`, `73401a0d` |
| Upstream-origin annotation detour | Tried a Service annotation to separate the Agent-facing hostname from the Backend origin and added coverage. Live testing worked, but this reintroduced a second declaration surface. | `d477e3f7`, `711de63b` |
| Final annotation-free design | Removed annotation support, derived both routing and Backend origin from the AIB protected resource, proved the single-name KIND rig through a test-only DNS split, and documented the manual AIB-native flow. | `f297c3b9`, `545ad81f`, `aee67830` |

The add-then-remove annotation commits remain in history intentionally; the branch was not rebased or squashed because it is stacked.

## Final live wire evidence

The final run reused `kind-kaos-te-eval` and contained no `ThirdPartyService` CRD, third-party annotation, or administrator-authored egress Kubernetes object.

| Check | Final annotation-free result |
|---|---|
| Reflected resources | Operator generated `Backend`, `HTTPRoute`, `SecurityPolicy`, and `EnvoyExtensionPolicy`; the Backend used the AIB protected-resource origin and the route reported `ResolvedRefs=True`. |
| Bound configuration | `agent-researcher` received `KAOS_TOKEN_EXCHANGE_CONFIG`; `agent-unbound` did not. |
| Consent flow | Empty vault produced application HTTP 200 with `third_party_reauth_required` and the AIB authorization URL; the S256 PKCE flow created the encrypted provider session. |
| Successful retry | Agent returned HTTP 200 with `Third-party tool completed.` |
| Re-minted claims | `azp=85be1caf-30b9-4236-87b2-fae29613d86d` (the researcher DCR client), `sub=c9df7bbc-c015-4095-b39e-7b5ed1a3f5e9`, and `aud=token-exchange-broker`. |
| Provider-token swap | The mock received `GET /api/data` with the exchanged token, decoded as `azp=mock-third-party-client`, `sub=mock-third-party-user`, `aud=mock-api`, scope `read`; it did not receive the Keycloak token. |
| Proven path | `researcher -> gateway -> PDP -> ext_proc -> generated Backend -> mock-api:80`, HTTP 200, with no routing loop. |
| Unbound Agent | Direct generated-route request returned HTTP 403 `ext_authz_denied`; ext_proc and the mock saw no request. |
| Vault revocation | Session deletion succeeded and left the vault empty; retry returned `third_party_reauth_required`, ext_proc observed broker HTTP 400 `invalid_grant`, and nothing reached the mock. |
| Internal traffic | Internal Agent-to-Agent call returned HTTP 200 with the original token (`azp=kaos`, same user `sub`); it was not re-minted or swapped and produced no ext_proc event. |
| Route isolation | The sole token-exchange `EnvoyExtensionPolicy` targeted only the operator-generated egress route. No internal route had ext_proc attached. |

## Dependencies and limitations

- Keycloak 26 must enable `token-exchange` and `admin-fine-grained-authz`. The `token-exchange-broker` target client needs management permissions, an explicit permission for each exchange-enabled Agent DCR client, and an audience mapper that emits exactly `aud=token-exchange-broker`. Missing configuration surfaces as exchange-time HTTP 400/403 failures.
- AIB owns the service, permission-set, consent, and vaulted-provider state. Production deployments require persistent AIB storage; KAOS does not store provider tokens.
- Reflection polls AIB every 45 seconds because AIB has no watch API. Changes converge on the next poll and remain fail-static while AIB is unreachable.
- AIB-side mistakes surface through operator events and runtime HTTP 403/reauthorization outcomes rather than a KAOS CRD status, because the AIB-native design deliberately has no third-party CRD.
- Exchange-enabled Agents require a Keycloak client for re-minting. ServiceAccount-primary Agents need a secondary Keycloak exchange credential or another explicitly designed trust path.
- The provider proven live was a mock OAuth/API service. Real-provider scope, refresh, and provider-side revocation behavior remain deployment-specific.
- The KIND-only single-name rig used Agent-pod `hostAliases` so the Agent resolved the protected hostname to the gateway while Envoy resolved that same hostname through CoreDNS to the mock Service. This is test infrastructure, not product configuration or an alternate-origin feature.

## Final validation state

The final rework reports record:

- Operator: `make test-unit` passed with Go 1.26.0 and OPA 1.18.2, including Rego tests and controller integration `45/45`.
- KAOS CLI: `126 passed` under pytest.
- Pydantic AI server: `349 passed, 10 skipped` under pytest.
- Pydantic AI server `ty`: all checks passed.
- Documentation: VitePress build passed.
- Generated lockfile churn was reverted; no product code changed during this report/PR refresh.

The manual production procedure and the clearly separated KIND-only rig are in `docs/examples/authorization.md` under **Manual AIB-native token-exchange runbook**. Detailed validation records are in `tmp/p20-rework-REPORT.md`, `tmp/p20-egress-REPORT.md`, and `tmp/p20-deannotate-REPORT.md`.
