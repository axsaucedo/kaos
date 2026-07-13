# Implementation report — delegated third-party access via AIB token exchange

This stacked feature adds opt-in delegated access to OAuth-protected third-party services. A requesting user's Keycloak token is re-minted for the acting Agent, AIB exchanges it for that user's vaulted provider token on one declared egress route, and the runtime surfaces consent/reconnection as a controlled URL outcome. The full flow passed on the wire on `feat/kaos-token-exchange` at `991db3b6`; the example documentation was then aligned with that evidence in `d7d4acb3`.

## Task overview

| Task | Status | Commit |
|---|---|---|
| Add the gated CLI install path for Keycloak + self-managed AIB/ext_proc | Complete | `d06f5e48` |
| Add the namespaced `ThirdPartyService` declaration, CRD, sample, and RBAC | Complete | `d65e7d58` |
| Project real AIB services, Agent registrations, and Agent-to-service permission sets | Complete | `d7c6dcd8` |
| Attach AIB ext_proc only to each declared third-party `HTTPRoute` | Complete | `cef3ea07` |
| Inject declared third-party targets into bound Agent runtimes | Complete | `7a8b6be6` |
| Re-mint delegated user tokens in `kaos_identity` for external calls | Complete | `e6834292` |
| Surface AIB consent/re-authentication URLs as controlled runtime outcomes | Complete | `739c739a` |
| Add the initial `.noeval` delegated-access walkthrough | Complete | `b5d26657` |
| Keep runtime `ty` validation clean | Complete | `ea6c5e5b` |
| Reconcile removal of an Agent egress binding | Complete | `36f90089` |
| Align the walkthrough with the passing wire evidence | Complete | `d7d4acb3` |

## Model as shipped

- Token exchange is feature-gated and off by default. `kaos system install --token-exchange-enabled --aib-chart-path <chart>` requires both Agent and user identity to use Keycloak; static provider credentials remain the default.
- AIB is exchange-only. It is not an Agent identity issuer and it does not authorize internal KAOS traffic.
- `ThirdPartyService` declares the provider `clientID`/`clientSecretRef`, issuer or explicit OAuth endpoints, scopes, protected resource URLs, one dedicated egress `routeRef`, and namespaced Agent/scope `access` bindings.
- The operator projects only exchange-enabled Agents, real third-party services, and real permission sets into AIB. It generates an `EnvoyExtensionPolicy` only for the declared egress route.
- For a declared external target, the runtime exchanges the normal user token through Keycloak using the acting Agent's DCR credential. The result keeps the user `sub`, changes `azp` to the Agent client, and has only `aud=token-exchange-broker`.
- AIB ext_proc validates the exchange inputs, grant, permission set, and vault session, then swaps the outbound authorization credential for the user's third-party token.
- Missing/expired/revoked consent is an expected failure contract: `third_party_reauth_required` plus an authorization URL. The caller completes OAuth and retries; the runtime does not silently retry or grant access.
- Internal calls retain the existing actor + propagated-user-token model and never traverse ext_proc.

## Live wire evidence

| Check | Result |
|---|---|
| User entry to `researcher` after consent | HTTP 200; `Third-party tool completed.` |
| Dedicated egress request | `GET /api/data`, HTTP 200, `response_code_details=via_upstream`, mock API independently logged the request |
| Re-minted token issuer | `http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos` |
| Re-minted token user | `sub=c9df7bbc-c015-4095-b39e-7b5ed1a3f5e9` |
| Re-minted token Agent | `azp=85be1caf-30b9-4236-87b2-fae29613d86d` |
| Re-minted token audience | `aud=token-exchange-broker` |
| Claim assertions | `azp` PASS, `sub` PASS, `aud` PASS |
| Vault revocation | Delete HTTP 200, `session terminated successfully`; subsequent list HTTP 200 with `sessions=[]` |
| Retry after revocation | Agent entry HTTP 200 with controlled `third_party_reauth_required`; ext_proc observed broker HTTP 400 `invalid_grant` and surfaced `/api/third-party/e535ec5d-f544-4403-b044-576c87ab317e/oauth2/authorize` |
| Internal Agent call | Entry HTTP 200; target `GET /health` HTTP 200; `Internal tool completed.` |
| Internal subject invariant | Original user token preserved (`azp=kaos`, same `sub`); no ext_proc event |
| Route invariant | Sole `EnvoyExtensionPolicy` targeted `github-mock-egress`; internal routes had ordinary `SecurityPolicy` attachments only |

The passing verification is recorded at `tmp/te-eval/evidence/verify/RESULT.md` in the evaluation workspace. The first attempt was invalidated by Docker-host pressure from four concurrent KIND clusters. The next attempt exposed a permanent in-process runtime deadlock. After the fixes below, the same flow completed promptly; no cluster work was repeated during this documentation/PR phase.

## Evaluation-found fixes

| Finding | Root cause and resolution | Commit |
|---|---|---|
| AIB Helm install rejected duplicate ext_proc environment names | The CLI duplicated chart-owned token endpoint/TLS variables; remove the duplicates | `11223b59` |
| Missing regression coverage for ext_proc wiring | Assert the rendered environment has one owner/value per setting | `711d1e1c` |
| Custom Agent did not retain KAOS-added toolsets | Extend the custom Agent's `_user_toolsets`, not the derived `_toolsets` collection | `840ac013` |
| Missing custom-Agent toolset regression coverage | Prove custom Agents receive the delegation/tool additions | `abc88da0` |
| Delegated calls deadlocked before network I/O | Globally patched `httpx.send` injected headers by minting an actor token under a non-reentrant lock; the mint itself re-entered the patch and attempted the same lock. Suppress instrumentation for identity-manager-owned mint requests | `d94f0946` |
| Missing deadlock regression coverage | Exercise managed mint under the global httpx patch and prove it completes | `f3d913cb` |
| Generic PDP denied valid external delegated traffic | Permit only verified actor + verified user-issuer subject with broker audience when no internal target exists; retain internal-route denial | `72026524` |
| Fresh Keycloak/AIB identity wiring was inconsistent | Enable Keycloak 26 exchange features, add the broker assertion audience, and validate the configured shared caller identity consistently | `991db3b6` |

## Keycloak 26 and AIB dependency notes

- Keycloak 26.0 requires `--features=token-exchange,admin-fine-grained-authz`. Without them the exchange endpoint returns HTTP 400 `unsupported_grant_type`.
- The `token-exchange-broker` target client must exist with management permissions enabled and a client policy/permission allowing each exchange-enabled Agent DCR client. Without it Keycloak returns HTTP 403 `Client not allowed to exchange`.
- The target exchange must produce exactly `aud=token-exchange-broker`, and the subject mapper must preserve the requesting user's `sub`.
- The shared ext_proc client assertion also needs the broker audience. The CLI wires this for new installs, but per-Agent exchange permissions remain an explicit deployment dependency.
- The evaluated Keycloak and AIB used ephemeral development state. Restarting Keycloak erased target-client/DCR permission state and rotated JWKS; production requires persistent state and declarative permission/mapper management.
- The AIB chart must include ext_proc. The feature currently requires a local unpublished chart path.

## Test state

- PAIS: 349 passed, 10 skipped; `ty`: all checks passed.
- CLI: 125 passed.
- Rego parity: 28/28 passed with OPA 1.18.1, including delegated-egress allow, wrong-audience deny, and internal-route deny.
- Operator `make test-unit`: passed using Go 1.26; integration suite 45/45 and all packages passed.
- VitePress: `npm run build` passed after the wire-aligned example update.
- All `uv.lock` churn was reverted.

## Deferred / not yet proven

- The passing provider was a mock. Real GitHub scopes, refresh behavior, and provider-side revocation remain to be exercised.
- ServiceAccount-primary Agents still need a secondary Keycloak exchange credential or a different exchange trust design.
- Stronger hardening should cross-check the delegated subject's Agent `azp` against the verified actor identity at the PDP/AIB boundary.
- The KAOS UI consent wrapper is deferred; the raw fail-with-URL -> authorize -> retry contract is shipped.
- A separate live unbound-Agent denial was not captured in the final verification, although projection and Rego tests cover missing bindings and invalid delegated inputs.
