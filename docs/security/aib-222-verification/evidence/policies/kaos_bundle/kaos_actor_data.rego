package aib.extproc.authz

import rego.v1

# Data-driven variant of kaos_actor.rego: the grant graph is NOT in the policy.
# It is loaded from a sibling data document (data.json -> data.kaos.grants),
# which in production KAOS would be regenerated from the Agent CRDs by the
# sync-service and served to #222 as a hot-reloadable OPA bundle.
#
# The rego rules below are static; only the data changes as CRDs change.

actor_token := t if {
	t := input.attributes.request.http.headers["x-agent-authorization"]
}

actor_sub := sub if {
	[_, payload, _] := io.jwt.decode(actor_token)
	sub := payload.sub
}

target_host := input.attributes.request.http.host

allow contains {"reason": sprintf("actor %v may reach %v", [actor_sub, target_host])} if {
	target_host in data.kaos.grants[actor_sub]
}

deny contains {"reason": "missing or invalid actor token"} if {
	not actor_sub
}

deny contains {"reason": sprintf("actor %v is not granted %v", [actor_sub, target_host])} if {
	actor_sub
	not target_host in data.kaos.grants[actor_sub]
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
