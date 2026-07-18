# User identity

The user identity plane carries the human subject independently of the agent actor. Keycloak is the current user OIDC provider.

## Gateway verification

When `security.userAuth.issuer` is configured, the operator adds a `user` JWT provider to each protected gateway `SecurityPolicy`. The provider reads the standard header:

```http
Authorization: Bearer <keycloak-user-jwt>
```

The gateway verifies the token against Keycloak through `remoteJWKS` and checks the configured issuer and optional audience. The PDP is authoritative for authorization and verifies the subject token again. The user provider is independent of `security.agentAuth.identity.provider`; Keycloak user tokens can accompany any supported agent issuer.

## Keycloak groups claim requirement

Group-based `AccessGrant`s require Keycloak access tokens to contain a `groups` claim. Configure a Group Membership protocol mapper with claim name `groups`, access-token claims enabled, and `full.path` set to `false`. KAOS therefore uses short group names: a Keycloak group named `researchers` appears as `"researchers"` in the claim and must be written as `name: researchers` in the `AccessGrant`.

This mapper is a hard requirement: without it, group-based grants cannot match. The CLI configures it automatically for the managed Keycloak preset. Bring-your-own-Keycloak deployments must configure the mapper themselves.

## AccessGrant

`AccessGrant` is a namespaced CRD that grants users or groups entry to selected resources. A `User` subject matches the token's `sub` or `email`; a `Group` subject matches a short name in the `groups` claim. Resources can name an explicit kind and name or select resources by label.

For example, this grant lets members of the Keycloak `researchers` group enter the `researcher` Agent in the same namespace:

```yaml
apiVersion: kaos.tools/v1alpha1
kind: AccessGrant
metadata:
  name: researchers-enter-researcher
  namespace: demo
spec:
  subjects:
    - kind: Group
      name: researchers
  resources:
    - kind: Agent
      name: researcher
```

The operator compiles this grant to `data.kaos.user_grants`, keyed as `group:researchers`. User entries are keyed as `user:<sub-or-email>`.

Check whether the grant is enforced with:

```bash
kubectl get accessgrant researchers-enter-researcher -n demo \
  -o jsonpath='{.status.conditions[?(@.type=="Enforced")]}'
```

Without a configured user identity provider, the object is accepted but its condition is `Enforced=False` with reason `NoUserIdentityProvider`, and it is not projected into policy data. Manual or disabled policy projection reports `PolicyProjectionInactive`, and a failed publication reports `ProjectionFailed`. The condition becomes `Enforced=True` only after automated policy projection successfully publishes the grant.

## User entry

A user reaches a protected Agent by sending a Keycloak access token in `Authorization` to the Agent's external gateway route. The request has no agent actor token at this entry edge. The PDP verifies the user subject and allows the request only when an enforced `AccessGrant` for the user's `sub`, `email`, or one of their `groups` covers the path-derived target Agent. The Agent then supplies its own actor token on internal calls while propagating the original user token as the required subject.

## Subject propagation

The agent runtime captures the inbound `Authorization` bearer token in request-local context and propagates it unchanged on outbound agent calls. The runtime also carries the principal and correlation context. On each hop:

- `Authorization` continues to represent the original user subject.
- `x-agent-authorization` represents the agent making that hop.

Header injection is additive. An explicitly set outbound `Authorization` header, such as a ModelAPI provider credential, is not overwritten.
