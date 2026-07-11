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
	if grep -qE "$pattern" <<<"$out"; then
		echo "ok   - $desc"
	else
		echo "FAIL - $desc (missing: $pattern)"
		FAIL=1
	fi
}

# assert PATTERN absent from the rendered output
refute() {
	local desc="$1" out="$2" pattern="$3"
	if grep -qE "$pattern" <<<"$out"; then
		echo "FAIL - $desc (unexpected: $pattern)"
		FAIL=1
	else
		echo "ok   - $desc"
	fi
}

# Default install: the removed provider selector is not rendered.
out="$(render)"
refute "authorization provider selector removed" "$out" 'SECURITY_AUTHORIZATION_PROVIDER'

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
	--set security.agentAuth.adminUrl=http://aib:8000/api)"
expect "broker admin url" "$out" 'AIB_ADMIN_URL:\s*"http://aib:8000/api"'

# Verified agent JWT verification mode.
out="$(render \
	--set security.agentAuth.authorization.agentJwtVerification=verified)"
expect "verified jwt mode" "$out" 'SECURITY_AUTHORIZATION_AGENT_JWT_VERIFICATION:\s*"verified"'

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
changed_out="$(render --set security.agentAuth.adminUrl=http://aib:8000/api)"
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
