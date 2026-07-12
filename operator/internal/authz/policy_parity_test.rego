package aib.extproc.authz

import rego.v1

# Parity coverage: the enforcement policy answers "can user A reach resource X via
# agent B" from one OPA input that carries all fact sources at once — the subject
# identity (Authorization header), the actor identity (x-agent-authorization
# header), and the requested resource (operator-owned gateway path) — evaluated
# against the projected grant graph. The same input shape backs both providers;
# only the grant facts differ in origin (KAOS-owned data here, broker
# granted_permission_sets for the broker provider).

# A demo-mode actor token (decoded, not verified) whose sub is the agent identity.
actor_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"sub": "kaos://agent/demo/researcher"},
	{"kty": "oct", "k": "c2VjcmV0"},
)

# A subject (user) token present in the same request, proving the subject fact is
# available alongside the actor and resource facts.
subject_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"sub": "user-alice@example.com"},
	{"kty": "oct", "k": "c2VjcmV0"},
)

serviceaccount_actor_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"sub": "system:serviceaccount:demo:kaos-agent-researcher"},
	{"kty": "oct", "k": "c2VjcmV0"},
)

request_input(path) := {
	"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject_jwt]),
		"x-agent-authorization": sprintf("Bearer %v", [actor_jwt]),
	}}}},
	"parsed_path": path,
}

grants := {"kaos://agent/demo/researcher": ["kaos://mcpserver/demo/github"]}
agents := {"kaos://agent/demo/researcher": {"issuer_sub": "system:serviceaccount:demo:kaos-agent-researcher"}}

test_allows_when_actor_granted_resource if {
	out := result with input as request_input(["demo", "mcp", "github"])
		with data.kaos.grants as grants
	out.action == "allow"
	out.allowed == true
}

test_denies_when_actor_not_granted_resource if {
	out := result with input as request_input(["demo", "mcp", "secret"])
		with data.kaos.grants as grants
	out.action == "deny"
}

test_denies_when_no_target_resource if {
	out := result with input as {"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject_jwt]),
		"x-agent-authorization": actor_jwt,
	}}}}}
		with data.kaos.grants as grants
	out.action == "deny"
}

test_denies_when_no_actor_token if {
	out := result with input as {"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject_jwt]),
	}}}}, "parsed_path": ["demo", "mcp", "github"]}
		with data.kaos.grants as grants
	out.action == "deny"
}

test_allows_serviceaccount_subject_via_agent_mapping if {
	serviceaccount_input := {
		"attributes": {"request": {"http": {"headers": {
			"x-agent-authorization": sprintf("Bearer %v", [serviceaccount_actor_jwt]),
		}}}},
		"parsed_path": ["demo", "mcp", "github"],
	}
	out := result with input as serviceaccount_input
		with data.kaos.grants as grants
		with data.kaos.agents as agents
	out.action == "allow"
}

test_denies_spoofed_granted_header_for_ungranted_path if {
	spoofed_input := {
		"attributes": {"request": {"http": {"headers": {
			"x-agent-authorization": sprintf("Bearer %v", [actor_jwt]),
			"x-kaos-target-resource": "kaos://mcpserver/demo/github",
		}}}},
		"parsed_path": ["demo", "mcp", "secret"],
	}
	out := result with input as spoofed_input
		with data.kaos.grants as grants
	out.allowed == false
	out.action == "deny"
}

test_allows_granted_resource_from_path_without_target_header if {
	path_input := {
		"attributes": {"request": {"http": {"headers": {
			"x-agent-authorization": sprintf("Bearer %v", [actor_jwt]),
		}}}},
		"parsed_path": ["demo", "mcp", "github", "tools", "call"],
	}
	out := result with input as path_input
		with data.kaos.grants as grants
	out.allowed == true
}
