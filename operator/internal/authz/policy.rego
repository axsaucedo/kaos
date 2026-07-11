package aib.extproc.authz

import rego.v1

# KAOS Model-1 coarse authorization policy.
#
# The policy is static; only the data it reads changes as KAOS resources change.
# It keys on the actor identity carried in the custom `x-agent-authorization`
# header and the target resource the request declares, and it checks the actor's
# grants in `data.kaos.grants` (projected by the operator from Agent CRDs).
#
# Verification is data-gated: when the operator injects an IdP JWKS at
# `data.kaos.jwks` (verified mode) the actor token signature is verified before
# its `sub` is trusted; when no JWKS is present (demo mode) the token is decoded
# without verification, which is spoofable and non-production.

actor_token := t if {
	t := input.attributes.request.http.headers["x-agent-authorization"]
}

# The resource the request targets, as the KAOS logical identity
# (kaos://<slug>/<ns>/<name>) stamped onto the request by the gateway route.
target_resource := r if {
	r := input.attributes.request.http.headers["x-kaos-target-resource"]
}

jwks_configured if {
	data.kaos.jwks
}

# Verified mode: a JWKS is configured, so the actor token signature must verify
# against it before the subject is trusted.
actor_sub := sub if {
	jwks_configured
	result := io.jwt.decode_verify(actor_token, {"cert": json.marshal(data.kaos.jwks)})
	result[0] == true
	sub := result[2].sub
}

# Demo mode: no JWKS configured, decode without verifying (spoofable).
actor_sub := sub if {
	not jwks_configured
	[_, payload, _] := io.jwt.decode(actor_token)
	sub := payload.sub
}

allow contains {"reason": sprintf("actor %v may reach %v", [actor_sub, target_resource])} if {
	target_resource in data.kaos.grants[actor_sub]
}

deny contains {"reason": "missing or invalid actor token"} if {
	not actor_sub
}

deny contains {"reason": "request declares no target resource"} if {
	actor_sub
	not target_resource
}

deny contains {"reason": sprintf("actor %v is not granted %v", [actor_sub, target_resource])} if {
	actor_sub
	target_resource
	not target_resource in data.kaos.grants[actor_sub]
}

result := {"action": "deny", "reasons": reasons} if {
	count(deny) > 0
	reasons := [entry.reason | some entry in deny]
}

result := {"action": "allow", "reasons": reasons} if {
	count(deny) == 0
	count(allow) > 0
	reasons := [entry.reason | some entry in allow]
}

default result := {"action": "deny", "reasons": ["no policy rule matched"]}
