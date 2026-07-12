package aib.extproc.authz

import rego.v1

# KAOS Model-1 coarse authorization policy.
#
# The policy is static; only the data it reads changes as KAOS resources change.
# It keys on the actor identity carried in the custom `x-agent-authorization`
# header and the target resource derived from the gateway path, and it checks the actor's
# grants in `data.kaos.grants` (projected by the operator from Agent CRDs).
#
# Actor identity is fail-closed: the token subject is trusted only after the
# configured issuer JWKS verifies its signature, algorithm, issuer, and audience.
# Missing or empty JWKS data leaves the actor undefined and denies the request.

actor_token := token if {
	raw := input.attributes.request.http.headers["x-agent-authorization"]
	[scheme, token] := split(raw, " ")
	lower(scheme) == "bearer"
}

actor_token := raw if {
	raw := input.attributes.request.http.headers["x-agent-authorization"]
	count(split(raw, " ")) == 1
}

resource_slug("mcp") := "mcpserver"

resource_slug(slug) := slug if {
	slug != "mcp"
}

# Derive the logical identity from the operator-owned gateway path. Route
# request-header modifiers run after ext_authz, so inbound headers are untrusted.
target_resource := sprintf("kaos://%v/%v/%v", [slug, input.parsed_path[0], input.parsed_path[2]]) if {
	count(input.parsed_path) >= 3
	slug := resource_slug(input.parsed_path[1])
}

jwks_configured if {
	data.kaos.jwks
}

unverified_actor_claims := payload if {
	[_, payload, _] := io.jwt.decode(actor_token)
}

allowed_actor_algorithms := {"RS256"}

# Fail closed: without a configured issuer JWKS, actor_sub remains undefined.
actor_sub := sub if {
	jwks_configured
	keys := data.kaos.jwks[unverified_actor_claims.iss]
	some algorithm in allowed_actor_algorithms
	result := io.jwt.decode_verify(actor_token, {
		"alg": algorithm,
		"aud": "kaos-gateway",
		"cert": json.marshal(keys),
		"iss": unverified_actor_claims.iss,
	})
	result[0] == true
	sub := result[2].sub
}

mapped_actor_id := id if {
	some id
	data.kaos.agents[id].issuer_sub == actor_sub
}

actor_id := mapped_actor_id if {
	mapped_actor_id
}

actor_id := actor_sub if {
	actor_sub
	not data.kaos.agents
}

allow contains {"reason": sprintf("actor %v may reach %v", [actor_id, target_resource])} if {
	target_resource in data.kaos.grants[actor_id]
}

deny contains {"reason": "missing or invalid actor token"} if {
	not actor_id
}

deny contains {"reason": "request declares no target resource"} if {
	actor_id
	not target_resource
}

deny contains {"reason": sprintf("actor %v is not granted %v", [actor_id, target_resource])} if {
	actor_id
	target_resource
	not target_resource in data.kaos.grants[actor_id]
}

result := {"allowed": false, "action": "deny", "reasons": reasons} if {
	count(deny) > 0
	reasons := [entry.reason | some entry in deny]
}

result := {"allowed": true, "action": "allow", "reasons": reasons} if {
	count(deny) == 0
	count(allow) > 0
	reasons := [entry.reason | some entry in allow]
}

default result := {"allowed": false, "action": "deny", "reasons": ["no policy rule matched"]}
