package aib.extproc.authz

import rego.v1

# Phase 2 (agentgateway HTTP e2e) actor policy.
#
# The agentgateway harness routes a single MCP backend, so the resource (host)
# axis is fixed; the HOST-based matrix was already proven at the ext_proc gRPC
# contract level in Phase 1 (opa_kaos_actor_test.go). This policy instead keys
# the tool-call decision on the ACTOR identity read from the x-agent-authorization
# header, to prove end-to-end over real HTTP through the proxy that:
#   1. agentgateway forwards the custom actor header to ext_proc,
#   2. the policy reads the actor and allows/denies, and
#   3. allow reaches the backend / deny is blocked on the wire.
#
# MCP lifecycle methods (initialize/ping/notifications) are allowed for everyone
# so the MCP client can establish a session regardless of actor — they are not
# resource access.

allowed_actors := {"agent-A"}

# Allow MCP lifecycle / non-tool methods (session setup, not resource access).
allow contains {"reason": "mcp lifecycle method"} if {
	input.type == "mcp_method"
}

allow contains {"reason": "mcp header-only"} if {
	input.type == "mcp_headers_only"
}

actor_sub := sub if {
	tok := input.attributes.request.http.headers["x-agent-authorization"]
	[_, payload, _] := io.jwt.decode(tok)
	sub := payload.sub
}

allow contains {"reason": sprintf("actor %v may call tools", [actor_sub])} if {
	input.type == "mcp_tool_call"
	actor_sub in allowed_actors
}

deny contains {"reason": "missing or invalid actor token"} if {
	input.type == "mcp_tool_call"
	not actor_sub
}

deny contains {"reason": sprintf("actor %v is not permitted to call tools", [actor_sub])} if {
	input.type == "mcp_tool_call"
	actor_sub
	not actor_sub in allowed_actors
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
