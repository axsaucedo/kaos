package aib.extproc.authz

import rego.v1

# KAOS coarse actor->resource authorization proof-of-concept.
#
# Demonstrates that an operator-supplied Rego policy running inside AIB #222's
# ext_proc OPA hook can enforce agent(actor)->resource allow/deny by reading the
# calling agent's identity from the x-agent-authorization actor token header and
# checking it against a static grant map keyed on the target host.
#
# The grant map mirrors what the KAOS sync-service would project from each Agent
# CRD's spec.agentNetwork.access (peer agents it may call) + spec.mcpServers
# (MCP servers it may reach):
#
#   Agent A: agentNetwork.access:[B]  mcpServers:[X]
#   Agent B: agentNetwork.access:[C]  mcpServers:[Y]
#
# so A may reach {mcp-x, agent-b}, B may reach {mcp-y, agent-c}.

grants := {
	"agent-A": {"mcp-x:9003", "agent-b:9003"},
	"agent-B": {"mcp-y:9003", "agent-c:9003"},
}

# The actor token is the current calling agent's identity, distinct from the
# user subject carried in Authorization. All request headers are present in the
# OPA input verbatim (no AIB-side redaction), so the policy can read it directly.
actor_token := t if {
	t := input.attributes.request.http.headers["x-agent-authorization"]
}

# Extract the agent identity (sub) from the actor token. io.jwt.decode does not
# verify the signature; a production KAOS policy would use io.jwt.decode_verify
# with the AIB JWKS. Signature verification is orthogonal to the axis under test.
actor_sub := sub if {
	[_, payload, _] := io.jwt.decode(actor_token)
	sub := payload.sub
}

target_host := input.attributes.request.http.host

allow contains {"reason": sprintf("actor %v may reach %v", [actor_sub, target_host])} if {
	target_host in grants[actor_sub]
}

# Fail closed on a missing/invalid actor token.
deny contains {"reason": "missing or invalid actor token"} if {
	not actor_sub
}

deny contains {"reason": sprintf("actor %v is not granted %v", [actor_sub, target_host])} if {
	actor_sub
	not target_host in grants[actor_sub]
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
