---
applyTo: "operator/**/*.go"
---

# Go Operator Instructions

## Quick Reference
```bash
cd operator
make generate manifests       # Regenerate CRD types and YAML
make test-unit                # Run Go unit tests (envtest)
make build                    # Build operator binary
make helm                     # Regenerate Helm chart from kustomize
```

## Project Structure
- `api/v1alpha1/`: CRD type definitions
- `controllers/`: Reconciler implementations
- `controllers/integration/`: Go integration tests with envtest
- `config/crd/bases/`: Generated CRD YAML files
- `chart/`: Helm chart (generated from kustomize)

## CRDs

For detailed information on the CRDs see the following documentation:

* docs/operator/agent-crd.md
* docs/operator/gateway-api.md
* docs/operator/mcpserver-crd.md
* docs/operator/modelapi-crd.md
* docs/operator/overview.md

View each respective file in case of making modifications to the respective module.

If any changes are introduced, this documentation must be updated accordingly.

## Authorization

Agent authorization is optional (off by default) and enforced at the gateway by an OPA policy inside the Envoy `ext_proc` filter. `AuthzProjectionReconciler` (`operator/controllers/authz_projection_controller.go`) projects a policy ConfigMap (`policy.rego` + `data.json`) from CRDs. Provider is `kaos` (KAOS-owned grants) or `aib` (broker permission sets). Modes: automated (project `policy.rego` + grants), bring-your-own ConfigMap (write nothing), operator-rego + admin data (`policy.rego` only), and broker external off-switch (identity only, no grants, prune forced off). Verification is `verified` (inject IdP JWKS at `data.kaos.jwks`, verify actor token) or `skip` (demo, spoofable, non-production). The `data.kaos.grants`/`data.kaos.jwks` schema is a published contract — see `operator/internal/authz/data-schema.md` and `docs/security/authorization.md`. Never write or prune policy data KAOS does not own.

## Key Commands
```bash
# After changing *_types.go files:
make generate manifests

# After changing controller logic:
make test-unit

# After changing kustomize config:
make helm
```

## RBAC Rules
RBAC is auto-generated from `// +kubebuilder:rbac:` annotations.
- Define controller RBAC in controller files
- Define leader election RBAC (leases, events) in `main.go`
- Never manually edit `config/rbac/role.yaml`

## Testing
- Unit tests use envtest (simulated K8s API)
- Tests are in `controllers/integration/` directory
- Use `client.Client` for K8s operations
- Test Ready conditions and status updates

## CRD Design Patterns
- Use `+kubebuilder:validation` for field validation
- Use `+optional` for optional fields
- Status should include `Conditions` for Ready/Failed states
- Use `ObservedGeneration` to track spec changes
- Agent CRD includes `AutonomousConfig` for self-looping execution (maps to `AUTONOMOUS_*` env vars)
