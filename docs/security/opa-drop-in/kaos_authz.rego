package kaos.authz

# Backend-neutral KAOS ext_authz policy for opa-envoy.
#
# This decides allow/deny over the SAME ext_authz contract the KAOS gateway
# already speaks to the default AIB access-check backend: the gateway passes
# the neutral resource/action as Envoy context extensions
# (`kaos.resource` / `kaos.action`) and the gateway-validated actor token as
# the bearer Authorization header. The decision is actor -> resource coverage,
# exactly mirroring AIB's permission-set `covers()` check, but sourced from the
# `data.kaos.grants` bundle instead of the broker's storage.
#
# opa-envoy is configured with `path: kaos/authz/allow`, so this boolean is the
# authorization decision (true = OkHttpResponse, false = denied).

import rego.v1

default allow := false

# The actor identity is the `sub` of the gateway-validated bearer token.
actor_sub := payload.sub if {
	auth := input.attributes.request.http.headers.authorization
	startswith(auth, "Bearer ")
	[_, payload, _] := io.jwt.decode(substring(auth, count("Bearer "), -1))
}

# Neutral resource/action injected by the gateway as context extensions.
resource := input.attributes.context_extensions["kaos.resource"]

action := input.attributes.context_extensions["kaos.action"]

# Allow when the actor holds a grant covering this resource + action.
allow if {
	some grant in data.kaos.grants[actor_sub]
	grant.resource == resource
	action in grant.actions
}
