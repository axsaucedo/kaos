package kaos.authz

import rego.v1

# Parity coverage: the enforcement policy answers "can user A reach resource X via
# agent B" from one OPA input that carries all fact sources at once — the subject
# identity (Authorization header), the actor identity (x-agent-authorization
# header), and the requested resource (operator-owned gateway path) — evaluated
# against the projected grant graph. The same input shape backs both providers;
# only the grant facts differ in origin (KAOS-owned data here, broker
# granted_permission_sets for the broker provider).

verified_issuer := "https://kubernetes.default.svc"
user_issuer := "https://users.example/realms/kaos"
wrong_issuer := "https://wrong.example"

verified_private_jwk := {
	"alg": "RS256",
	"d": "Fx-xsp8YrFSRa1thpaNBkQUPVeAk1tH_9SMwZMo6NZyiol6TKOss60nHLEQ-C-OCw_dupSazHbB8uGkRs1GUmsvoF0PRIm3vT4rdp6pNNDna2ySULiKd-htcAgb17T7bfd1YhSiLJgcx9XS0vVb6rfnkJcQWNwdnAl1ZUjQ7ypV4F1o_L5Dd9JcoVMTibO3XN1ZnDBs9UhzBgctLI-zEPyMhYA57Bp6nOkYMwlWhcaZgJTyHrD0jB6hMlVcL9RQlOZjmJHdxnX5OnsKuCoAopCFU1f7i3Ob024hlSkCLLNnVUq4KTiYCx0n9xrGj1ld1Pq6x6j4CnxKjkZYQic7o0Q",
	"dp": "YbYWmJiHtN5hiLYAuICfCdiBcuAQc6NUdY8Up2geRFd174gousniBKIkW3293mischAL7fq0sfaJP7iHOwRL4wMYlL62ksy8603IIO4zPhxX2ACrpfcwU4Hs3AldvH6M82eeUCCzp5-L4zYT6bANOVbPeN4yk04J3NtHFvR5HcE",
	"dq": "wGWzVF0eT-tcCDtdISXcAFx883V9vI1uozPq9Fg3xkKpBG4wz_wN5OvGvG7TuwRewiyRBNKn_kxncmyHcwsQn_BiHrd3G7_i-TFFzOjMR7LpHem2nmwuizzFtX0Yc6M6H6St0vr6utaPV8Z3iot0Twy0C6T9YF2JOAMo3-__fy0",
	"e": "AQAB",
	"kid": "kaos-test",
	"kty": "RSA",
	"n": "o9ZEw_zcv2ygbW9wL5dTPAh6jrrmBmEn2lY3fXpXrtJMszWCEZCw7_jC-Hz5zwwLHIHfoDQvq0zHyp22DP9Ds6V31oUkhokqR4LKCqK7dx_fExOI0-R0whV4fVzr5iKf9emCihZhTC3QHE2u5p4mw4xHtW2s8BIs0dnFP-MpSt0ZugkDVjvzKyf8vVp65ANPK96C11zrxQCHa9BmFbfgnvLlCIRhCIZs1qbhG1eySynZK1KSTAXHgWO205QYPmLttXzbcXlDmXh12S1jQYrFGuOeAvarH-WPiHqS8toNONZ1tIchzPaI05qCcXfc6UsJXw0vn4Ic1Ke3yvapaGwkNw",
	"p": "0i2TkPLLUBMCYOyv1HQ3V1iWZS0Hy3ediHLk7pjVltoTFNrucn6Ldwtm23wP9y6jxCV9pcgqDO7aT0PZCxZGCRDeSe8WxBpY3NWDbyGLE6hlzf58ErXgsvQSZo9S5T_nJU-RJ8BPHk8Cvtk9zhcdJpVdh_8FSgu9RtuACRq4Q3E",
	"q": "x45QHX84hebZECnEyO-D0kz8AUYjB5r75PI1j_KQy6fu2alFFmBFoB16QHEekGnEsiayazfoBNCYl5Nk59re1IPUNRkBXcGmXknISs1BXpFKixvNwvZ_wCD_3xSdK4EIPHn0_qJDOvigf6m3QTvR_BkyZPO-hDzP0T8zCZsMvic",
	"qi": "WVX8QmZsplHXZ1PsT-J5JyG-9RlT0hVErhVSRgqBTNic9Hzt4eeR2eRn1ZX3A3vlolQlO0vrXwXj-wgXEubSsZYZWGbE0LMHycB2iB22Xj513rbnrROJU9DtREjIQA3-EQtIsaCGTOZG7W5pJwqCPXRcLGvFE1JIKuJ1SCfYffU",
	"use": "sig",
}

verified_jwks := {"keys": [{
	"alg": "RS256",
	"e": verified_private_jwk.e,
	"kid": verified_private_jwk.kid,
	"kty": verified_private_jwk.kty,
	"n": verified_private_jwk.n,
	"use": verified_private_jwk.use,
}]}

configured_jwks := {
	verified_issuer: verified_jwks,
	user_issuer: verified_jwks,
	wrong_issuer: verified_jwks,
}

user_config := {"issuer": user_issuer, "audience": "kaos-users"}
actor_sub := "system:serviceaccount:demo:kaos-agent-researcher"
autonomous_sub := "system:serviceaccount:demo:kaos-agent-autonomous"
non_autonomous_sub := "system:serviceaccount:demo:kaos-agent-worker"

signed_token(issuer, audience, subject, extra) := io.jwt.encode_sign(
	{"alg": "RS256", "kid": "kaos-test"},
	object.union({"aud": audience, "iss": issuer, "sub": subject}, extra),
	verified_private_jwk,
)

actor_jwt := signed_token(verified_issuer, ["kaos-gateway"], actor_sub, {})
oidc_actor_jwt := signed_token(user_issuer, ["kaos-gateway"], "keycloak-service-account-uuid", {"azp": "oidc-client-1"})
unmapped_oidc_actor_jwt := signed_token(user_issuer, ["kaos-gateway"], "other-service-account-uuid", {"azp": "unmapped-client"})
autonomous_subject_jwt := signed_token(verified_issuer, ["kaos-gateway"], autonomous_sub, {})
shared_issuer_autonomous_subject_jwt := signed_token(user_issuer, ["kaos-gateway"], autonomous_sub, {})
shared_issuer_user_subject_jwt := signed_token(user_issuer, ["kaos-users"], autonomous_sub, {})
non_autonomous_subject_jwt := signed_token(verified_issuer, ["kaos-gateway"], non_autonomous_sub, {})
user_subject_jwt := signed_token(user_issuer, ["kaos-users"], "user-123", {"email": "alice@example.com", "groups": ["writers", "readers"]})
user_subject_without_email_jwt := signed_token(user_issuer, ["kaos-users"], "user-123", {})
wrong_audience_subject_jwt := signed_token(user_issuer, ["another-service"], "user-123", {"email": "alice@example.com"})
delegated_subject_jwt := signed_token(user_issuer, ["token-exchange-broker"], "user-123", {"azp": "oidc-client-1"})
wrong_issuer_subject_jwt := signed_token(wrong_issuer, ["kaos-users"], "user-123", {"email": "alice@example.com"})
forged_subject_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"aud": ["kaos-users"], "iss": user_issuer, "sub": "user-123", "email": "alice@example.com"},
	{"kty": "oct", "k": "Zm9yZ2Vk"},
)

internal_input(actor, subject, path) := {
	"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject]),
		"x-agent-authorization": sprintf("Bearer %v", [actor]),
	}}}},
	"parsed_path": path,
}

actor_only_input := {
	"attributes": {"request": {"http": {"headers": {
		"x-agent-authorization": sprintf("Bearer %v", [actor_jwt]),
	}}}},
	"parsed_path": ["demo", "mcp", "github"],
}

entry_path_input(subject, path) := {
	"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject]),
	}}}},
	"parsed_path": path,
}

entry_input(subject) := entry_path_input(subject, ["demo", "agent", "writer"])

egress_input(actor, subject) := internal_input(actor, subject, ["api", "data"])

empty_input := {
	"attributes": {"request": {"http": {"headers": {}}}},
	"parsed_path": ["demo", "agent", "writer"],
}

grants := {"kaos://agent/demo/researcher": ["kaos://mcpserver/demo/github"]}
agents := {
	"kaos://agent/demo/researcher": {"issuer_sub": actor_sub, "autonomous": false},
	"kaos://agent/demo/autonomous": {"issuer_sub": autonomous_sub, "autonomous": true},
	"kaos://agent/demo/worker": {"issuer_sub": non_autonomous_sub, "autonomous": false},
	"kaos://agent/demo/oidc": {"issuer_azp": "oidc-client-1", "autonomous": true},
}

user_grants := {
	"user:alice@example.com": ["kaos://agent/demo/writer"],
	"user:user-123": ["kaos://agent/demo/by-sub"],
	"group:writers": ["kaos://agent/demo/group-writer"],
}

test_internal_actor_granted_with_autonomous_subject_allows if {
	out := result with input as internal_input(actor_jwt, autonomous_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
}

test_oidc_actor_azp_resolves_to_logical_grant if {
	oidc_grants := {"kaos://agent/demo/oidc": ["kaos://mcpserver/demo/github"]}
	out := result with input as internal_input(oidc_actor_jwt, user_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as oidc_grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
	"actor kaos://agent/demo/oidc may reach kaos://mcpserver/demo/github for a verified subject" in out.reasons
}

test_unmapped_oidc_actor_denies if {
	oidc_grants := {"kaos://agent/demo/oidc": ["kaos://mcpserver/demo/github"]}
	out := result with input as internal_input(unmapped_oidc_actor_jwt, user_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as oidc_grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
	"missing or invalid actor token" in out.reasons
}

test_oidc_autonomous_subject_azp_resolves_to_mapping if {
	out := result with input as internal_input(actor_jwt, oidc_actor_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
}

test_internal_shared_issuer_autonomous_subject_allows if {
	out := result with input as internal_input(actor_jwt, shared_issuer_autonomous_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
}

test_shared_issuer_user_audience_is_not_an_autonomous_subject if {
	out := result with input as entry_input(shared_issuer_user_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
		with data.kaos.user_grants as {}
	out.allowed == false
	"user is not granted target resource" in out.reasons
}

test_internal_autonomous_subject_without_user_provider_allows if {
	out := result with input as internal_input(actor_jwt, autonomous_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as {verified_issuer: verified_jwks}
		with data.kaos.agents as agents
	out.allowed == true
}

test_internal_actor_granted_with_user_subject_allows if {
	out := result with input as internal_input(actor_jwt, user_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
}

test_delegated_egress_with_verified_actor_and_subject_allows if {
	out := result with input as egress_input(actor_jwt, delegated_subject_jwt)
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
	"actor kaos://agent/demo/researcher may perform delegated third-party egress" in out.reasons
}

test_delegated_egress_wrong_subject_audience_denies if {
	out := result with input as egress_input(actor_jwt, user_subject_jwt)
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
	"request declares no target resource" in out.reasons
}

test_delegated_subject_is_not_accepted_on_internal_route if {
	out := result with input as internal_input(actor_jwt, delegated_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
	"subject missing or invalid" in out.reasons
}

test_internal_actor_alone_without_subject_denies if {
	out := result with input as actor_only_input
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
	"subject missing or invalid" in out.reasons
}

test_internal_non_autonomous_agent_subject_denies if {
	out := result with input as internal_input(actor_jwt, non_autonomous_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
}

test_internal_ungranted_actor_with_valid_subject_denies if {
	out := result with input as internal_input(actor_jwt, user_subject_jwt, ["demo", "mcp", "secret"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
}

test_entry_user_grant_by_principal_allows if {
	out := result with input as entry_input(user_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == true
}

test_entry_user_grant_by_group_allows if {
	out := result with input as entry_path_input(user_subject_jwt, ["demo", "agent", "group-writer"])
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == true
}

test_entry_user_grant_by_sub_when_email_missing_allows if {
	out := result with input as entry_path_input(user_subject_without_email_jwt, ["demo", "agent", "by-sub"])
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == true
}

test_entry_user_without_matching_grant_denies if {
	out := result with input as entry_input(user_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as {}
	out.allowed == false
}

test_entry_without_subject_denies if {
	out := result with input as empty_input
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
	out.allowed == false
}

test_entry_forged_subject_denies if {
	out := result with input as entry_input(forged_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == false
}

test_entry_wrong_audience_subject_denies if {
	out := result with input as entry_input(wrong_audience_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == false
}

test_entry_wrong_issuer_subject_denies if {
	out := result with input as entry_input(wrong_issuer_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == false
}

test_entry_missing_jwks_denies if {
	out := result with input as entry_input(user_subject_jwt)
		with data.kaos.user as user_config
		with data.kaos.user_grants as user_grants
	out.allowed == false
}

test_entry_missing_user_configuration_denies if {
	out := result with input as entry_input(user_subject_jwt)
		with data.kaos.jwks as configured_jwks
		with data.kaos.user_grants as user_grants
	out.allowed == false
}

test_internal_invalid_actor_denies_with_valid_subject if {
	wrong_actor := signed_token(verified_issuer, ["wrong-audience"], actor_sub, {})
	out := result with input as internal_input(wrong_actor, user_subject_jwt, ["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
	"missing or invalid actor token" in out.reasons
}

test_internal_missing_target_denies if {
	request := internal_input(actor_jwt, user_subject_jwt, ["demo"])
	out := result with input as request
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
}

test_internal_spoofed_target_header_does_not_override_path if {
	request := {
		"attributes": {"request": {"http": {"headers": {
			"authorization": sprintf("Bearer %v", [user_subject_jwt]),
			"x-agent-authorization": sprintf("Bearer %v", [actor_jwt]),
			"x-kaos-target-resource": "kaos://mcpserver/demo/github",
		}}}},
		"parsed_path": ["demo", "mcp", "secret"],
	}
	out := result with input as request
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == false
}

test_internal_granted_memorystore_path_allows_with_valid_subject if {
	memory_grants := {"kaos://agent/demo/researcher": ["kaos://memorystore/demo/brain"]}
	out := result with input as internal_input(actor_jwt, user_subject_jwt, ["demo", "memorystore", "brain", "v1", "recall"])
		with data.kaos.grants as memory_grants
		with data.kaos.jwks as configured_jwks
		with data.kaos.agents as agents
		with data.kaos.user as user_config
	out.allowed == true
}
