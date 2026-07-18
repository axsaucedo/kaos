package kaos.authz

import rego.v1

# KAOS coarse authorization policy. Every request requires a verified subject.
# Internal hops additionally require a verified actor with a grant for the
# operator-owned target path. Entry requests require a verified user subject
# with a user or group grant for that target.

allowed_token_algorithms := {"RS256"}

actor_header := input.attributes.request.http.headers["x-agent-authorization"]

actor_present if {
	actor_header != ""
}

actor_token := token if {
	[scheme, token] := split(actor_header, " ")
	lower(scheme) == "bearer"
}

actor_token := actor_header if {
	count(split(actor_header, " ")) == 1
}

subject_token := token if {
	raw := input.attributes.request.http.headers.authorization
	[scheme, token] := split(raw, " ")
	lower(scheme) == "bearer"
}

resource_slug("mcp") := "mcpserver"

resource_slug(slug) := slug if {
	slug != "mcp"
}

# Derive the logical identity only from the operator-owned gateway path. Route
# request-header modifiers run after ext_authz, so inbound headers are untrusted.
target_resource := sprintf("kaos://%v/%v/%v", [slug, input.parsed_path[0], input.parsed_path[2]]) if {
	count(input.parsed_path) >= 3
	slug := resource_slug(input.parsed_path[1])
}

# Trust claims only after the token algorithm, issuer, audience, and signature
# verify against the JWKS selected by the token's untrusted issuer claim.
verify_token(token, expected_audience) := claims if {
	[_, unverified, _] := io.jwt.decode(token)
	keys := data.kaos.jwks[unverified.iss]
	some algorithm in allowed_token_algorithms
	verified := io.jwt.decode_verify(token, {
		"alg": algorithm,
		"aud": expected_audience,
		"cert": json.marshal(keys),
		"iss": unverified.iss,
	})
	verified[0] == true
	claims := verified[2]
}

actor_claims := verify_token(actor_token, "kaos-gateway")

agent_claim_matches(agent, claims) if {
	agent.issuer_sub == claims.sub
}

agent_claim_matches(agent, claims) if {
	agent.issuer_azp == claims.azp
}

mapped_actor_id := id if {
	some id
	agent_claim_matches(data.kaos.agents[id], actor_claims)
}

actor_id := mapped_actor_id if {
	mapped_actor_id
}

actor_id := actor_claims.sub if {
	actor_claims.sub
	not data.kaos.agents
}

user_name(claims) := claims.email if {
	claims.email != ""
}

user_name(claims) := claims.sub if {
	claims.sub != ""
	object.get(claims, "email", "") == ""
}

user_subject := {"principal_key": principal_key, "group_keys": group_keys} if {
	claims := verify_token(subject_token, data.kaos.user.audience)
	claims.iss == data.kaos.user.issuer
	name := user_name(claims)
	principal_key := sprintf("user:%v", [name])
	group_keys := [sprintf("group:%v", [group]) | some group in object.get(claims, "groups", [])]
}

autonomous_subject if {
	claims := verify_token(subject_token, "kaos-gateway")
	some id
	agent_claim_matches(data.kaos.agents[id], claims)
	data.kaos.agents[id].autonomous == true
}

delegated_egress if {
	actor_present
	actor_id
	not target_resource
	claims := verify_token(subject_token, "token-exchange-broker")
	claims.iss == data.kaos.user.issuer
	claims.sub != ""
	claims.azp == data.kaos.agents[actor_id].issuer_azp
}

subject_valid if {
	user_subject
}

subject_valid if {
	autonomous_subject
}

user_granted(subject, resource) if {
	resource in data.kaos.user_grants[subject.principal_key]
}

user_granted(subject, resource) if {
	some group_key in subject.group_keys
	resource in data.kaos.user_grants[group_key]
}

allow contains {"reason": sprintf("actor %v may reach %v for a verified subject", [actor_id, target_resource])} if {
	actor_present
	target_resource in data.kaos.grants[actor_id]
	subject_valid
}

allow contains {"reason": sprintf("user subject may reach %v", [target_resource])} if {
	not actor_present
	user_granted(user_subject, target_resource)
}

allow contains {"reason": sprintf("actor %v may perform delegated third-party egress", [actor_id])} if {
	delegated_egress
}

deny contains {"reason": "missing or invalid actor token"} if {
	actor_present
	not actor_id
}

deny contains {"reason": "request declares no target resource"} if {
	actor_present
	actor_id
	not target_resource
	not delegated_egress
}

deny contains {"reason": sprintf("actor %v is not granted %v", [actor_id, target_resource])} if {
	actor_present
	actor_id
	target_resource
	not target_resource in data.kaos.grants[actor_id]
}

deny contains {"reason": "subject missing or invalid"} if {
	actor_present
	not subject_valid
	not delegated_egress
}

deny contains {"reason": "no user subject at entry"} if {
	not actor_present
	not user_subject
}

deny contains {"reason": "request declares no target resource"} if {
	not actor_present
	user_subject
	not target_resource
}

deny contains {"reason": "user is not granted target resource"} if {
	not actor_present
	user_subject
	target_resource
	not user_granted(user_subject, target_resource)
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
