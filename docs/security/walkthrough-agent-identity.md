# Agent identity

The agent identity plane authenticates the agent making each hop. KAOS selects one actor-token issuer through `security.agentAuth.identity.provider`: `serviceaccount`, `oidc`, or `aib`. Every issuer must mint a JWT for the `kaos-gateway` audience.

## ServiceAccount issuer

`serviceaccount` is the zero-dependency default. The operator creates an owned Kubernetes ServiceAccount for each Agent and mounts a projected token at `/var/run/secrets/kaos-agent/token`. `AGENT_AUTH_TOKEN_FILE` points the runtime to that path.

Kubelet mints and rotates the short-lived projected token. The runtime reads the file whenever it needs the actor token, so it sees rotated tokens without restarting. The token subject has the form `system:serviceaccount:<namespace>:<serviceaccount-name>`.

At startup, the operator discovers the Kubernetes issuer and JWKS from the API server. Gateway `SecurityPolicy` resources use `localJWKS` with those inline keys and require the `kaos-gateway` audience.

## AIB issuer

`aib` uses the Agentic Identity Broker as the actor-token issuer. The operator registers each Agent with AIB and writes its client id and client secret to a per-agent Secret. Agent pods receive the provider-neutral `AGENT_AUTH_CLIENT_ID`, `AGENT_AUTH_CLIENT_SECRET_FILE`, and `AGENT_AUTH_TOKEN_ENDPOINT` settings.

The runtime uses OAuth `client_credentials` to obtain a short-lived actor token. It caches the token until refresh is needed, rereads the mounted client-secret file so Secret rotation is visible, and refreshes and retries once after a gateway 401. AIB owns credential and token issuance; it does not make resource authorization decisions.

The configured AIB issuer is the token `iss` value used by all verifiers. Gateway `SecurityPolicy` resources use `remoteJWKS` at the broker JWKS endpoint and require the `kaos-gateway` audience.

## OIDC issuer

`oidc` is the issuer-selection abstraction for agent OAuth clients. Dynamic Client Registration (DCR), including per-agent client creation and credential delivery, is forthcoming. It is not an operational agent-identity flow today.

The existing abstraction reserves the same provider-neutral runtime contract used by broker credentials: an issuer and token endpoint plus per-agent client credentials. A complete OIDC/DCR implementation must mint short-lived actor tokens for the `kaos-gateway` audience and publish signing keys for gateway and PDP verification.

## Actor identity data

The operator publishes issuer data in the policy ConfigMap:

- `data.kaos.jwks` maps the exact actor-token issuer to its JWKS. The PDP selects this entry from `iss` and verifies the signature, exact issuer, `RS256` algorithm, and `kaos-gateway` audience.
- `data.kaos.agents` maps a logical actor id such as `kaos://agent/demo/researcher` to its issuer-specific `issuer_sub`. This resolves a verified token `sub` to the KAOS actor used by authorization.

ServiceAccount subjects require this mapping because their Kubernetes subject is not a KAOS resource id. Issuers that use the logical actor id directly as `sub` can be resolved without a mapping when no agent map is present.

The agent sends its token on every protected hop:

```http
x-agent-authorization: Bearer <actor-jwt>
```

The runtime replaces the actor identity at each agent hop with the current agent's own token. The user subject, when present, is propagated independently.
