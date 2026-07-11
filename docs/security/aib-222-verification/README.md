# AIB #222 OPA-in-ext_proc — agent→resource authorization verification

This directory records an empirical verification of whether AIB's upstream `#222` OPA-in-ext_proc authorization can enforce coarse **agent(actor)→resource** allow/deny for KAOS's multi-agent delegation model using only an operator-supplied Rego policy, with minimal or no changes to AIB. It captures the findings, the concrete gaps that KAOS must handle, and the reproducible test evidence used to reach them.

The verification was run against the real `#222` ext_proc code (the actual gRPC `Process()` flow and OPA authorizer) and, at the HTTP layer, against a real agentgateway proxy (Envoy-based ext_proc) in Docker. Only the token-exchange endpoint and the MCP backend were mocked.

This is the ext_proc counterpart to the ext_authz sample in [`../opa-drop-in`](../opa-drop-in). The `opa-drop-in` sample demonstrates the Envoy **ext_authz** contract (`kaos.resource`/`kaos.action` context extensions); this document covers the AIB `#222` **ext_proc** path (token exchange + OPA on the buffered MCP body), which is a different integration surface.

## TL;DR

- An operator-supplied Rego policy **can** enforce agent→resource allow/deny by reading a custom actor header, with **no AIB code changes**. Headers reach Rego verbatim, grants can be data-driven (a bundle), and the decision is fail-closed.
- Three structural properties of `#222` mean KAOS cannot adopt it as-is for all its patterns without additional handling: (1) authorization is skipped entirely when there is no `Authorization` bearer (breaks autonomous agents), (2) the OPA allow path is coupled to a successful token exchange, and (3) the exchange is subject-only, so it cannot carry a per-hop acting-agent identity (the `azp`-freeze / actor_token gap).

## What was verified (holds today, no AIB changes)

- **Custom actor header reaches Rego verbatim.** The policy reads `x-agent-authorization`, decodes the JWT `sub`, and decides on it. Over the agentgateway proxy, a denied call produced the exact reason `actor agent-B is not permitted to call tools`, proving the proxy forwarded the custom header to ext_proc and the policy read the actor identity.
- **Agent→resource matrix enforced at the ext_proc contract level.** A KAOS-shaped grant graph (Agent A → resources {mcp-x, agent-b}; Agent B → resources {mcp-y, agent-c}) was enforced across the A/B/X/Y matrix, including the A→B delegation edge, keyed on the actor rather than the user subject.
- **Grants can be data-driven, not hardcoded.** The same behavior was proven both with the graph inline in the policy and with the graph supplied as OPA data (`data.kaos.grants`) from a bundle directory — i.e. the permission graph can be synced as data rather than baked into the policy.
- **Allow vs deny on the wire.** Over real HTTP through agentgateway: an allowed tool call reaches the backend carrying the exchanged token; a denied tool call is blocked and never reaches the backend. MCP lifecycle methods (initialize/notifications) are allowed by the policy so a session can be established regardless of actor.

## Gaps found (require KAOS handling or an AIB extension)

- **G1 — Autonomous / no-bearer bypass (structural).** `#222` gates OPA behind the presence of an `Authorization` bearer: a request with no bearer passes through **without evaluating OPA** and reaches the backend unauthorized. This was proven end-to-end over HTTP — an ungranted actor with no bearer still reached the backend. KAOS autonomous agents (self-looping, no user token) would therefore bypass authorization entirely. Closing this needs either an AIB extension (evaluate OPA on the actor even when there is no user subject) or a KAOS guarantee that every hop carries a bearer/actor token.
- **G2 — Exchange-before-OPA coupling.** For body-bearing requests, ext_proc performs the token exchange in the RequestHeaders phase and only then evaluates OPA on the buffered body in the RequestBody phase. Authorization is coupled to the token-exchange (impersonation) path; a KAOS integration cannot get an OPA decision without also going through the exchange.
- **G3 — Subject-only exchange (azp-freeze / actor_token gap).** The exchange sends the subject token only, plus a fixed gateway `client_assertion`, and caches keyed on subject+resource. The forwarded token's `azp` stays pinned to the first agent, so in a chain A→B→C, B's forwarded token still reads `azp=A`. The exchange path cannot distinguish the acting agent. Keying the Rego on a KAOS-supplied actor header side-steps this **for allow/deny**, but the token handed to upstream services still carries the wrong `azp`; downstream services that authorize on `azp` remain mis-attributed. This is the motivation for the optional RFC 8693 `actor_token` ask.
- **G4 — Proxy / contract caveat.** Verified with agentgateway (Envoy-based ext_proc). KAOS today assumes the ext_authz contract; the ext_proc contract differs and requires **body mode** (OPA needs the parsed MCP method, not headers only). Whichever proxy KAOS runs must forward the actor header (agentgateway does; confirm for the chosen proxy).

## What KAOS would need to adopt #222-OPA for agent→resource authz

- Provide the operator-authored Rego (path or bundle mode) and sync the grant graph into `data.kaos.grants`.
- Inject a per-hop acting-agent identity header (e.g. `x-agent-authorization`) at each agent runtime, so the policy keys on the real caller of each hop.
- Run ext_proc in body mode so OPA sees the parsed MCP method (KAOS's current assumption is header-only ext_authz).
- Handle the autonomous no-bearer case (G1) — either an AIB extension or a per-hop bearer/actor token invariant.

## Evidence

- `evidence/policies/kaos_actor.rego` — actor→resource policy (graph inline), reads `x-agent-authorization`, decodes JWT `sub`, fail-closed.
- `evidence/policies/kaos_bundle/{data.json,kaos_actor_data.rego}` — the data-driven variant: grants as OPA data, policy references `data.kaos.grants`.
- `evidence/policies/kaos_actor_agentgw.rego` — the HTTP/agentgateway policy: allows MCP lifecycle for all actors, gates tool calls on the actor.
- `evidence/opa_kaos_actor_test.go.txt` — the ext_proc gRPC-contract test (A/B/X/Y matrix, data-driven grants, no-bearer gap, unknown-actor fail-closed).
- `evidence/opa_kaos_actor_agentgw_test.go.txt` — the HTTP end-to-end test through agentgateway (allow reaches backend with exchanged token, deny blocked, no-bearer autonomous gap).

The `.go` tests are stored with a `.txt` suffix because they depend on AIB-internal packages and are not part of the KAOS build; they are included as reproducible evidence to run inside an AIB checkout.

## Reproduce (inside an AIB checkout with `#222`)

Copy the policies into `tests/e2e/extproc/fixtures/policies/` and the tests (renamed back to `.go`) into `tests/e2e/extproc/`, then:

```bash
cd tests/e2e/extproc
# ext_proc gRPC-contract matrix (no Docker required)
go test -run TestExtProcTokenExchange -args -ginkgo.focus="KAOS actor" -ginkgo.v
# HTTP end-to-end through agentgateway (requires Docker)
go test -run TestExtProcTokenExchange -args -ginkgo.focus="KAOS actor->resource authorization via agentgateway" -ginkgo.v
```
