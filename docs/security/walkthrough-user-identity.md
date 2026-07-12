# User identity

The user identity plane carries the human subject independently of the agent actor. Keycloak is the current user OIDC provider.

## Gateway verification

When `security.userAuth.issuer` is configured, the operator adds a `user` JWT provider to each protected gateway `SecurityPolicy`. The provider reads the standard header:

```http
Authorization: Bearer <keycloak-user-jwt>
```

The gateway verifies the token against Keycloak through `remoteJWKS`, checks the configured issuer and optional audience, and maps `sub` and `preferred_username` to trusted request headers. The user provider is independent of `security.agentAuth.identity.provider`; Keycloak user tokens can accompany any supported agent issuer.

## Keycloak groups claim requirement

Group-based `AccessGrant`s require Keycloak access tokens to contain a `groups` claim. Configure a Group Membership protocol mapper with claim name `groups`, access-token claims enabled, and `full.path` set to `false`. KAOS therefore uses short group names: a Keycloak group named `researchers` appears as `"researchers"` in the claim and must be written as `name: researchers` in the `AccessGrant`.

This mapper is a hard requirement: without it, group-based grants cannot match. The CLI configures it automatically for the managed Keycloak preset. Bring-your-own-Keycloak deployments must configure the mapper themselves.

## Subject propagation

The agent runtime captures the inbound `Authorization` bearer token in request-local context and propagates it unchanged on outbound agent calls. The runtime also carries the principal and correlation context. On each hop:

- `Authorization` continues to represent the original user subject.
- `x-agent-authorization` represents the agent making that hop.

Header injection is additive. An explicitly set outbound `Authorization` header, such as a ModelAPI provider credential, is not overwritten.

User-to-resource authorization through `AccessGrant` is forthcoming. The gateway verifies configured user tokens today, but the shipped PDP policy does not use the user subject in its allow or deny decision.
