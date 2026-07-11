// Package authz renders the static KAOS Model-1 authorization policy and the
// per-cluster grant data the external authorization engine reads. The policy is
// a compiled-in constant; only the data changes
// as KAOS resources change.
package authz

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed policy.rego
var policyRego string

const (
	// PolicyKey is the ConfigMap key holding the static rego policy.
	PolicyKey = "policy.rego"
	// DataKey is the ConfigMap key holding the projected grant data document.
	DataKey = "data.json"
	// PolicyPackage is the rego package the enforcement engine queries.
	PolicyPackage = "aib.extproc.authz"
	// DecisionPath is the rule the enforcement engine reads for the decision.
	DecisionPath = "result"
)

// Policy returns the static rego policy asset.
func Policy() string {
	return policyRego
}

// DataDocument builds the OPA data document from the projected grant map and,
// when verification is enabled, the IdP JWKS. The grants are placed at
// `data.kaos.grants` and the JWKS, when supplied, at `data.kaos.jwks`; the
// presence of the JWKS is what switches the policy from demo (decode) to
// verified (decode_verify) mode.
func DataDocument(grants map[string][]string, jwks map[string]any) ([]byte, error) {
	if grants == nil {
		grants = map[string][]string{}
	}
	kaos := map[string]any{"grants": grants}
	if jwks != nil {
		kaos["jwks"] = jwks
	}
	doc := map[string]any{"kaos": kaos}
	out, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("marshalling authorization data: %w", err)
	}
	return out, nil
}

// ConfigMapData returns the ConfigMap payload (policy + data) the operator
// writes for the enforcement engine to mount and load.
func ConfigMapData(grants map[string][]string, jwks map[string]any) (map[string]string, error) {
	data, err := DataDocument(grants, jwks)
	if err != nil {
		return nil, err
	}
	return map[string]string{
		PolicyKey: policyRego,
		DataKey:   string(data),
	}, nil
}
