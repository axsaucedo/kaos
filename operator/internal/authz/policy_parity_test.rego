package kaos.authz

import rego.v1

# Parity coverage: the enforcement policy answers "can user A reach resource X via
# agent B" from one OPA input that carries all fact sources at once — the subject
# identity (Authorization header), the actor identity (x-agent-authorization
# header), and the requested resource (operator-owned gateway path) — evaluated
# against the projected grant graph. The same input shape backs both providers;
# only the grant facts differ in origin (KAOS-owned data here, broker
# granted_permission_sets for the broker provider).

actor_jwt := io.jwt.encode_sign(
	{"alg": "RS256", "kid": "kaos-test"},
	{"aud": ["kaos-gateway"], "iss": verified_issuer, "sub": "kaos://agent/demo/researcher"},
	verified_private_jwk,
)

# A subject (user) token present in the same request, proving the subject fact is
# available alongside the actor and resource facts.
subject_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"sub": "user-alice@example.com"},
	{"kty": "oct", "k": "c2VjcmV0"},
)

serviceaccount_actor_jwt := io.jwt.encode_sign(
	{"alg": "RS256", "kid": "kaos-test"},
	{"aud": ["kaos-gateway"], "iss": verified_issuer, "sub": "system:serviceaccount:demo:kaos-agent-researcher"},
	verified_private_jwk,
)

verified_issuer := "https://kubernetes.default.svc"

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

configured_jwks := {verified_issuer: verified_jwks}

verified_actor_jwt(audience) := io.jwt.encode_sign(
	{"alg": "RS256", "kid": "kaos-test"},
	{"aud": audience, "iss": verified_issuer, "sub": "system:serviceaccount:demo:kaos-agent-researcher"},
	verified_private_jwk,
)

verified_actor_jwt_without_audience := io.jwt.encode_sign(
	{"alg": "RS256", "kid": "kaos-test"},
	{"iss": verified_issuer, "sub": "system:serviceaccount:demo:kaos-agent-researcher"},
	verified_private_jwk,
)

disallowed_algorithm_actor_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"aud": ["kaos-gateway"], "iss": verified_issuer, "sub": "system:serviceaccount:demo:kaos-agent-researcher"},
	{"kty": "oct", "k": "c2VjcmV0"},
)

forged_actor_jwt := io.jwt.encode_sign(
	{"alg": "HS256"},
	{"sub": "kaos://agent/demo/researcher"},
	{"kty": "oct", "k": "Zm9yZ2Vk"},
)

request_input(path) := {
	"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject_jwt]),
		"x-agent-authorization": sprintf("Bearer %v", [actor_jwt]),
	}}}},
	"parsed_path": path,
}

verified_request_input(token) := {
	"attributes": {"request": {"http": {"headers": {
		"x-agent-authorization": sprintf("Bearer %v", [token]),
	}}}},
	"parsed_path": ["demo", "mcp", "github"],
}

grants := {"kaos://agent/demo/researcher": ["kaos://mcpserver/demo/github"]}
agents := {"kaos://agent/demo/researcher": {"issuer_sub": "system:serviceaccount:demo:kaos-agent-researcher"}}

test_allows_when_actor_granted_resource if {
	out := result with input as request_input(["demo", "mcp", "github"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
	out.action == "allow"
	out.allowed == true
}

test_denies_when_actor_not_granted_resource if {
	out := result with input as request_input(["demo", "mcp", "secret"])
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
	out.action == "deny"
}

test_denies_when_no_target_resource if {
	out := result with input as {"attributes": {"request": {"http": {"headers": {
		"authorization": sprintf("Bearer %v", [subject_jwt]),
		"x-agent-authorization": actor_jwt,
	}}}}}
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
	out.action == "deny"
}

test_denies_when_no_actor_token if {
	out := result with input as {
		"attributes": {"request": {"http": {"headers": {
			"authorization": sprintf("Bearer %v", [subject_jwt]),
		}}}},
		"parsed_path": ["demo", "mcp", "github"],
	}
		with data.kaos.grants as grants
		with data.kaos.jwks as configured_jwks
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
		with data.kaos.jwks as configured_jwks
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
		with data.kaos.jwks as configured_jwks
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
		with data.kaos.jwks as configured_jwks
	out.allowed == true
}

test_allows_granted_memorystore_resource_from_path if {
	memory_grants := {"kaos://agent/demo/researcher": ["kaos://memorystore/demo/brain"]}
	out := result with input as request_input(["demo", "memorystore", "brain", "v1", "recall"])
		with data.kaos.grants as memory_grants
		with data.kaos.jwks as configured_jwks
	out.allowed == true
}

test_verified_allows_correct_serviceaccount_issuer_algorithm_and_audience if {
	out := result with input as verified_request_input(verified_actor_jwt(["kaos-gateway"]))
		with data.kaos.grants as grants
		with data.kaos.jwks as {verified_issuer: verified_jwks}
		with data.kaos.agents as agents
	out.allowed == true
}

test_verified_denies_missing_audience if {
	out := result with input as verified_request_input(verified_actor_jwt_without_audience)
		with data.kaos.grants as grants
		with data.kaos.jwks as {verified_issuer: verified_jwks}
		with data.kaos.agents as agents
	out.allowed == false
}

test_verified_denies_wrong_audience if {
	out := result with input as verified_request_input(verified_actor_jwt(["another-service"]))
		with data.kaos.grants as grants
		with data.kaos.jwks as {verified_issuer: verified_jwks}
		with data.kaos.agents as agents
	out.allowed == false
}

test_verified_denies_disallowed_algorithm if {
	out := result with input as verified_request_input(disallowed_algorithm_actor_jwt)
		with data.kaos.grants as grants
		with data.kaos.jwks as {verified_issuer: verified_jwks}
		with data.kaos.agents as agents
	out.allowed == false
}

test_denies_forged_token_when_jwks_not_configured if {
	missing_jwks := result with input as verified_request_input(forged_actor_jwt)
		with data.kaos.grants as grants
	missing_jwks.allowed == false
	missing_jwks.reasons == ["missing or invalid actor token"]

	empty_jwks := result with input as verified_request_input(forged_actor_jwt)
		with data.kaos.grants as grants
		with data.kaos.jwks as {}
	empty_jwks.allowed == false
	empty_jwks.reasons == ["missing or invalid actor token"]
}
