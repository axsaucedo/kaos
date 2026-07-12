#!/usr/bin/env bash
# Renders the operator chart across the authorization mode combinations and
# asserts the operator ConfigMap carries the expected settings for each mode.
set -euo pipefail

CHART_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0

render() {
	helm template t "$CHART_DIR" "$@" 2>/dev/null
}

# assert PATTERN present in the rendered output for a described case
expect() {
	local desc="$1" out="$2" pattern="$3"
	if grep -qE -- "$pattern" <<<"$out"; then
		echo "ok   - $desc"
	else
		echo "FAIL - $desc (missing: $pattern)"
		FAIL=1
	fi
}

# assert PATTERN absent from the rendered output
refute() {
	local desc="$1" out="$2" pattern="$3"
	if grep -qE -- "$pattern" <<<"$out"; then
		echo "FAIL - $desc (unexpected: $pattern)"
		FAIL=1
	else
		echo "ok   - $desc"
	fi
}

# Default install: the removed provider selector is not rendered.
out="$(render)"
refute "authorization provider selector removed" "$out" 'SECURITY_AUTHORIZATION_PROVIDER'
refute "PDP disabled by default" "$out" 'name: kaos-pdp'
refute "disabled PDP does not enable operator enforcement" "$out" 'SECURITY_PDP_ENABLED'
expect "ServiceAccount identity is default" "$out" 'SECURITY_AGENT_AUTH_IDENTITY_PROVIDER:\s*"serviceaccount"'

out="$(render \
	--set security.agentAuth.identity.provider=aib \
	--set security.agentAuth.issuer=https://agents.example.test)"
expect "AIB issuer reaches operator from one chart value" "$out" 'SECURITY_AGENT_AUTH_ISSUER:\s*"https://agents.example.test"'
if [[ "$(grep -c 'SECURITY_AGENT_AUTH_ISSUER:' <<<"$out")" -eq 1 ]]; then
	echo "ok   - AIB issuer rendered once"
else
	echo "FAIL - AIB issuer rendered more than once"
	FAIL=1
fi

out="$(render \
	--set security.agentAuth.identity.provider=serviceaccount \
	--set security.agentAuth.issuer=http://ignored-issuer \
	--set security.agentAuth.adminUrl=http://ignored-admin \
	--set security.agentAuth.credentialSecretPrefix=ignored-secret)"
expect "ServiceAccount identity selected" "$out" 'SECURITY_AGENT_AUTH_IDENTITY_PROVIDER:\s*"serviceaccount"'
expect "ServiceAccount audience rendered" "$out" 'SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_AUDIENCE:\s*"kaos-gateway"'
expect "ServiceAccount expiration rendered" "$out" 'SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_EXPIRATION_SECONDS:\s*"3600"'
expect "ServiceAccount token path rendered" "$out" 'SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_TOKEN_PATH:\s*"/var/run/secrets/kaos-agent/token"'
refute "ServiceAccount identity omits AIB issuer" "$out" 'SECURITY_AGENT_AUTH_ISSUER'
refute "ServiceAccount identity omits AIB admin" "$out" 'AIB_ADMIN_URL'
refute "ServiceAccount identity omits credential Secret prefix" "$out" 'SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX'

out="$(render \
	--set security.agentAuth.identity.provider=oidc \
	--set security.agentAuth.issuer=https://issuer.example \
	--set security.agentAuth.adminUrl=http://ignored-admin \
	--set security.agentAuth.credentialSecretPrefix=ignored-secret)"
expect "OIDC identity selected" "$out" 'SECURITY_AGENT_AUTH_IDENTITY_PROVIDER:\s*"oidc"'
expect "OIDC issuer rendered" "$out" 'SECURITY_AGENT_AUTH_ISSUER:\s*"https://issuer.example"'
refute "OIDC identity omits AIB admin" "$out" 'AIB_ADMIN_URL'
refute "OIDC identity omits credential Secret prefix" "$out" 'SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX'

if invalid_identity="$(helm template t "$CHART_DIR" --set security.agentAuth.identity.provider=invalid 2>&1)"; then
	echo "FAIL - invalid identity provider was accepted"
	FAIL=1
elif grep -q 'must be one of: serviceaccount, oidc, aib' <<<"$invalid_identity"; then
	echo "ok   - invalid identity provider rejected clearly"
else
	echo "FAIL - invalid identity provider error was unclear"
	FAIL=1
fi

# PDP renders stock OPA, its gRPC Service, policy mount, and HA budget.
out="$(render \
	--namespace kaos-system \
	--set security.pdp.enabled=true \
	--set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
	--set security.agentAuth.projection.policyConfigMap.namespace=kaos-system)"
expect "PDP deployment rendered" "$out" 'kind: Deployment'
expect "PDP service rendered" "$out" 'kind: Service'
expect "PDP service name" "$out" 'name: kaos-pdp'
expect "PDP gRPC port" "$out" 'port: 9191'
expect "PDP decision path" "$out" 'plugins.envoy_ext_authz_grpc.path=kaos/authz/result'
expect "PDP watches mounted policy" "$out" -- '--watch'
expect "PDP loads Rego file without ConfigMap symlink recursion" "$out" '/policy/policy.rego'
expect "PDP loads data file without ConfigMap symlink recursion" "$out" '/policy/data.json'
expect "PDP policy ConfigMap mounted" "$out" 'name: kaos-authz-policy'
expect "PDP enablement reaches operator" "$out" 'SECURITY_PDP_ENABLED:\s*"true"'
expect "PDP ext_authz URL defaults to Service" "$out" 'SECURITY_AGENT_AUTH_EXT_AUTHZ_URL:\s*"kaos-pdp.kaos-system.svc:9191"'
expect "PDP disruption budget rendered" "$out" 'kind: PodDisruptionBudget'
expect "PDP disruption budget keeps one replica" "$out" 'minAvailable: 1'

out="$(render \
	--namespace kaos-system \
	--set security.pdp.enabled=true \
	--set security.pdp.replicas=1 \
	--set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
	--set security.agentAuth.projection.policyConfigMap.namespace=kaos-system)"
refute "single-replica PDP omits disruption budget" "$out" 'kind: PodDisruptionBudget'

out="$(render \
	--namespace kaos-system \
	--set security.pdp.enabled=true \
	--set security.agentAuth.extAuthzUrl=custom-authz.custom-system.svc:9002 \
	--set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
	--set security.agentAuth.projection.policyConfigMap.namespace=kaos-system)"
expect "explicit ext_authz URL overrides PDP default" "$out" 'SECURITY_AGENT_AUTH_EXT_AUTHZ_URL:\s*"custom-authz.custom-system.svc:9002"'
refute "PDP default omitted when override set" "$out" 'SECURITY_AGENT_AUTH_EXT_AUTHZ_URL:\s*"kaos-pdp.kaos-system.svc:9191"'

if mismatch="$(helm template t "$CHART_DIR" \
	--namespace kaos-system \
	--set security.pdp.enabled=true \
	--set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
	--set security.agentAuth.projection.policyConfigMap.namespace=other-system 2>&1)"; then
	echo "FAIL - cross-namespace PDP policy mount was accepted"
	FAIL=1
elif grep -q 'Pods cannot mount ConfigMaps across namespaces' <<<"$mismatch"; then
	echo "ok   - cross-namespace PDP policy mount rejected clearly"
else
	echo "FAIL - cross-namespace PDP policy mount error was unclear"
	FAIL=1
fi

# Automated policy data source with a policy ConfigMap target.
out="$(render \
	--set security.agentAuth.authorization.policyDataSource=automated \
	--set security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy \
	--set security.agentAuth.projection.policyConfigMap.namespace=aib-system)"
expect "automated data source" "$out" 'SECURITY_AUTHORIZATION_POLICY_DATA_SOURCE:\s*"automated"'
expect "policy configmap name" "$out" 'AUTHZ_POLICY_CONFIGMAP_NAME:\s*"kaos-authz-policy"'
expect "policy configmap namespace" "$out" 'AUTHZ_POLICY_CONFIGMAP_NAMESPACE:\s*"aib-system"'

# Operator-rego override (admin authors the grant data).
out="$(render \
	--set security.agentAuth.authorization.policyDataSource=manual \
	--set security.agentAuth.authorization.policyRegoOverride=true)"
expect "rego override set" "$out" 'SECURITY_AUTHORIZATION_POLICY_REGO_OVERRIDE:\s*"true"'
expect "manual data source" "$out" 'SECURITY_AUTHORIZATION_POLICY_DATA_SOURCE:\s*"manual"'

# Broker identity provisioning is independent of policy compilation.
out="$(render \
	--set security.agentAuth.identity.provider=aib \
	--set security.agentAuth.adminUrl=http://aib:8000/api)"
expect "broker admin url" "$out" 'AIB_ADMIN_URL:\s*"http://aib:8000/api"'

# ext_authz enforcement backend.
out="$(render \
	--set security.agentAuth.extAuthzUrl=http://authz:9000)"
expect "ext_authz url" "$out" 'SECURITY_AGENT_AUTH_EXT_AUTHZ_URL:\s*"http://authz:9000"'
refute "gateway extension selector removed" "$out" 'SECURITY_AUTHORIZATION_GATEWAY_EXTENSION'
refute "ext_proc backend removed" "$out" 'SECURITY_AGENT_AUTH_EXT_PROC_URL'

# The controller-manager pod carries a config checksum so that changes to the
# operator ConfigMap (e.g. enabling agent auth) roll the pod automatically.
default_out="$(render)"
expect "config checksum annotation present" "$default_out" 'checksum/config:\s*[0-9a-f]{64}'
default_sum="$(grep -oE 'checksum/config:\s*[0-9a-f]{64}' <<<"$default_out" | grep -oE '[0-9a-f]{64}')"
changed_out="$(render --set security.agentAuth.identity.provider=aib --set security.agentAuth.adminUrl=http://aib:8000/api)"
changed_sum="$(grep -oE 'checksum/config:\s*[0-9a-f]{64}' <<<"$changed_out" | grep -oE '[0-9a-f]{64}')"
if [[ "$default_sum" != "$changed_sum" ]]; then
	echo "ok   - config checksum changes when the ConfigMap changes"
else
	echo "FAIL - config checksum did not change when the ConfigMap changed"
	FAIL=1
fi

if [[ "$FAIL" -ne 0 ]]; then
	echo "chart authorization render tests FAILED"
	exit 1
fi
echo "chart authorization render tests PASSED"
