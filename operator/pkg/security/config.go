// Package security provides operator-wide configuration for resource-level
// authorization enforcement at the gateway. When configured, the operator
// attaches an external authorization (ext_authz) check to protected routes so
// that requests are allowed or denied based on the calling agent's granted
// permissions.
package security

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config holds operator-wide security configuration read from the environment.
// Security is enabled when any gateway enforcement hook is configured — either
// the ext_authz access-check backend or the ext_proc token-exchange/OPA backend
// (see SecurityEnabled). Credential mounting and NetworkPolicy generation are
// gated on that broader predicate so they stay active for ext_proc-only installs
// rather than being tied to ext_authz alone.
type Config struct {
	// ExtAuthzURL is the host:port of the external authorization (ext_authz)
	// access-check gRPC backend (agentAuth.extAuthzUrl). An empty value means
	// gateway authorization enforcement is disabled.
	ExtAuthzURL string

	// Issuer is the agent-auth OIDC issuer URL (agentAuth.issuer): the broker
	// that mints agent actor tokens. It is propagated to agent pods so they can
	// obtain an actor token from their mounted credentials.
	Issuer string

	// CredentialSecretPrefix is the name prefix of the per-agent credential
	// Secret provisioned by the identity projection controller (agentAuth.credentialSecretPrefix).
	// An empty value disables credential mounting into agent pods.
	CredentialSecretPrefix string

	// UserIssuer is the user-auth OIDC issuer URL (userAuth.issuer): the identity
	// provider (e.g. Keycloak) that issues human user subject tokens. When set, a
	// user jwt_authn provider is emitted on protected routes. Empty means no user
	// provider is generated (agent-only / autonomous installs).
	UserIssuer string

	// UserAudience is the expected audience claim for user subject tokens
	// (userAuth.audience). Validated by the user jwt_authn provider when set.
	UserAudience string

	// UserJWKSURIOverride optionally overrides the user provider's JWKS endpoint
	// (userAuth.jwksUri). When empty it is derived from UserIssuer using the
	// standard OIDC realm path.
	UserJWKSURIOverride string

	// ExtProcURL is the host:port of the AIB external-processing (ext_proc)
	// token-exchange gRPC backend (agentAuth.extProcUrl). When set, the operator
	// emits an EnvoyExtensionPolicy on protected routes so the gateway can perform
	// an RFC 8693 token exchange and replace the upstream Authorization header.
	// An empty value means token-exchange is disabled and existing routing is
	// unchanged. It is independent of ExtAuthzURL.
	ExtProcURL string

	// GatewayNamespace is the namespace of the Envoy Gateway data plane
	// (security.gatewayNamespace). It is the ingress source allowed by the
	// generated NetworkPolicy so the Gateway can reach protected workloads. An
	// empty value defaults to "envoy-gateway-system".
	GatewayNamespace string

	// OperatorNamespace is the namespace the operator runs in. It is the ingress
	// source allowed by the generated NetworkPolicy so the operator can still poll
	// workload ClusterIP status endpoints. It is read from SECURITY_OPERATOR_NAMESPACE,
	// falling back to POD_NAMESPACE; an empty value defaults to "kaos-system".
	OperatorNamespace string

	// NetworkPolicyDisabled is an escape hatch (security.networkPolicy.enabled=false)
	// that suppresses NetworkPolicy generation even when security is operational, for
	// CNIs that misbehave or clusters that manage isolation externally.
	NetworkPolicyDisabled bool

	// NetworkPolicyEgress opts generated NetworkPolicies into egress
	// isolation. It is intentionally separate from NetworkPolicyDisabled because
	// egress enforcement can break provider calls on CNIs that enforce it.
	NetworkPolicyEgress bool

	// GatewayHost is the host[:port] of the Envoy Gateway as reachable from inside
	// the cluster (security.gatewayHost). When gateway routing is enabled and this
	// is set, the operator injects gateway-routed URLs into agents so internal
	// agent->MCP/ModelAPI/peer traffic flows through the gateway (where jwt_authn,
	// ext_authz and ext_proc apply) instead of directly to the workload Service. An
	// empty value lets the controller resolve the host from the Gateway resource's
	// status address.
	GatewayHost string

	// GatewayRouting enables injecting gateway-routed endpoint URLs into agents
	// (security.gatewayRouting.enabled). Default off so existing installs keep using
	// direct Service URLs; it is enabled together with NetworkPolicy to force the
	// gateway to be the only application path between workloads.
	GatewayRouting bool

	// AuthorizationModel selects which coarse authorization model(s) the operator
	// projects and enforces at the ext_proc OPA decision point
	// (security.authorization.model). Empty means authorization projection is off.
	AuthorizationModel AuthorizationModel

	// EnforcementMode selects the gateway enforcement path
	// (security.authorization.enforcement). Defaults to OPA embedded in ext_proc;
	// the legacy ext_authz seam is opt-in.
	EnforcementMode EnforcementMode

	// VerificationMode selects how the actor token is trusted
	// (security.authorization.verification). Empty derives the mode from the agent
	// issuer: verified when an issuer is configured, demo (header-trust) otherwise.
	VerificationMode VerificationMode

	// PopulatorMode selects who owns the authorization policy data
	// (security.authorization.populator). Defaults to operator CRD projection.
	PopulatorMode PopulatorMode
}

// AuthorizationModel selects which coarse authorization model(s) the operator
// projects and enforces. Both models share one OPA decision point in ext_proc;
// they differ only in where the grant facts live.
type AuthorizationModel string

const (
	// AuthorizationModelOff disables authorization projection (default).
	AuthorizationModelOff AuthorizationModel = ""
	// AuthorizationModelData enforces from KAOS-owned OPA data (data.kaos.grants)
	// derived from CRDs — the actor-keyed "Model 1" path.
	AuthorizationModelData AuthorizationModel = "model1"
	// AuthorizationModelBroker enforces from broker permission sets returned by
	// token exchange (granted_permission_sets) — the "Model 2" path.
	AuthorizationModelBroker AuthorizationModel = "model2"
	// AuthorizationModelBoth exposes both fact sources to the policy at once.
	AuthorizationModelBoth AuthorizationModel = "both"
)

// EnforcementMode selects the gateway enforcement path.
type EnforcementMode string

const (
	// EnforcementExtProc enforces via OPA embedded in the ext_proc filter (default).
	EnforcementExtProc EnforcementMode = "extproc"
	// EnforcementExtAuthz enforces via the optional, default-off ext_authz seam.
	EnforcementExtAuthz EnforcementMode = "extauthz"
)

// VerificationMode selects how the actor (agent) token is trusted by the policy.
type VerificationMode string

const (
	// VerificationDemo trusts the actor header without signature verification —
	// spoofable and non-production; used when no issuer is configured.
	VerificationDemo VerificationMode = "demo"
	// VerificationVerified requires the actor token signature to be verified
	// against the injected JWKS.
	VerificationVerified VerificationMode = "verified"
)

// PopulatorMode selects who owns the authorization policy data the operator
// enforces against.
type PopulatorMode string

const (
	// PopulatorCRD projects the policy data from KAOS CRDs (default, authoritative).
	PopulatorCRD PopulatorMode = "crd"
	// PopulatorBYOConfigMap points enforcement at an admin-provided ConfigMap the
	// operator does not manage (Model 1 bring-your-own).
	PopulatorBYOConfigMap PopulatorMode = "byo-configmap"
	// PopulatorOperatorRego lets the operator own the rego while an admin authors
	// the data key (Model 1 operator-rego + admin-data).
	PopulatorOperatorRego PopulatorMode = "operator-rego"
	// PopulatorExternal turns projection off and leaves AIB authoritative,
	// forcing prune off while KAOS keeps identity (Model 2 off-switch).
	PopulatorExternal PopulatorMode = "external"
)

const (
	envExtAuthzURL            = "SECURITY_AGENT_AUTH_EXT_AUTHZ_URL"
	envExtProcURL             = "SECURITY_AGENT_AUTH_EXT_PROC_URL"
	envIssuer                 = "SECURITY_AGENT_AUTH_ISSUER"
	envCredentialSecretPrefix = "SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX"
	envUserIssuer             = "SECURITY_USER_AUTH_ISSUER"
	envUserAudience           = "SECURITY_USER_AUTH_AUDIENCE"
	envUserJWKSURI            = "SECURITY_USER_AUTH_JWKS_URI"
	envGatewayNamespace       = "SECURITY_GATEWAY_NAMESPACE"
	envOperatorNamespace      = "SECURITY_OPERATOR_NAMESPACE"
	envPodNamespace           = "POD_NAMESPACE"
	envNetworkPolicyDisabled  = "SECURITY_NETWORK_POLICY_DISABLED"
	envNetworkPolicyEgress    = "SECURITY_NETWORK_POLICY_EGRESS_ENABLED"
	envGatewayHost            = "SECURITY_GATEWAY_HOST"
	envGatewayRouting         = "SECURITY_GATEWAY_ROUTING_ENABLED"
	envAuthorizationModel     = "SECURITY_AUTHORIZATION_MODEL"
	envEnforcementMode        = "SECURITY_AUTHORIZATION_ENFORCEMENT"
	envVerificationMode       = "SECURITY_AUTHORIZATION_VERIFICATION"
	envPopulatorMode          = "SECURITY_AUTHORIZATION_POPULATOR"
)

// Default namespaces used by NetworkPolicy ingress rules when not configured.
const (
	defaultGatewayNamespace  = "envoy-gateway-system"
	defaultOperatorNamespace = "kaos-system"
)

// GetConfig reads security configuration from environment variables.
func GetConfig() Config {
	operatorNamespace := os.Getenv(envOperatorNamespace)
	if strings.TrimSpace(operatorNamespace) == "" {
		operatorNamespace = os.Getenv(envPodNamespace)
	}
	return Config{
		ExtAuthzURL:            os.Getenv(envExtAuthzURL),
		Issuer:                 os.Getenv(envIssuer),
		CredentialSecretPrefix: os.Getenv(envCredentialSecretPrefix),
		UserIssuer:             os.Getenv(envUserIssuer),
		UserAudience:           os.Getenv(envUserAudience),
		UserJWKSURIOverride:    os.Getenv(envUserJWKSURI),
		ExtProcURL:             os.Getenv(envExtProcURL),
		GatewayNamespace:       os.Getenv(envGatewayNamespace),
		OperatorNamespace:      operatorNamespace,
		NetworkPolicyDisabled:  parseBoolEnv(envNetworkPolicyDisabled),
		NetworkPolicyEgress:    parseBoolEnv(envNetworkPolicyEgress),
		GatewayHost:            os.Getenv(envGatewayHost),
		GatewayRouting:         parseBoolEnv(envGatewayRouting),
		AuthorizationModel:     AuthorizationModel(readEnumEnv(envAuthorizationModel)),
		EnforcementMode:        EnforcementMode(readEnumEnv(envEnforcementMode)),
		VerificationMode:       VerificationMode(readEnumEnv(envVerificationMode)),
		PopulatorMode:          PopulatorMode(readEnumEnv(envPopulatorMode)),
	}
}

// parseBoolEnv reads a boolean environment variable, returning false when the
// variable is unset or not a recognizable truthy value.
func parseBoolEnv(key string) bool {
	v, err := strconv.ParseBool(strings.TrimSpace(os.Getenv(key)))
	if err != nil {
		return false
	}
	return v
}

// readEnumEnv reads a string environment variable, trimming whitespace and
// lower-casing it so enum comparisons are case-insensitive. Validation and
// defaulting happen in the typed accessors.
func readEnumEnv(key string) string {
	return strings.ToLower(strings.TrimSpace(os.Getenv(key)))
}

// normalizeEnum returns v when it matches one of the allowed values, otherwise
// def. It keeps unknown or unset configuration on a safe default.
func normalizeEnum[T ~string](v T, allowed []T, def T) T {
	for _, a := range allowed {
		if v == a {
			return v
		}
	}
	return def
}

// IsOperational reports whether the legacy ext_authz access-check backend is
// configured. It gates ext_authz SecurityPolicy generation specifically; broader
// security behavior (credentials, NetworkPolicy) is gated on SecurityEnabled.
func (c Config) IsOperational() bool {
	return strings.TrimSpace(c.ExtAuthzURL) != ""
}

// SecurityEnabled reports whether any gateway enforcement hook is configured —
// either the ext_authz access-check backend or the ext_proc token-exchange/OPA
// backend. It is the predicate that keeps credential mounting and NetworkPolicy
// generation active independently of ext_authz, so an ext_proc-only install
// (OPA-in-ext_proc authorization) still provisions credentials and isolation.
func (c Config) SecurityEnabled() bool {
	return c.IsOperational() || c.ExtProcEnabled()
}

// CredentialMountingEnabled reports whether the operator should mount per-agent
// AIB credentials into agent pods. This requires security to be enabled (any
// enforcement hook, not ext_authz specifically) and a credential Secret prefix to
// be configured.
func (c Config) CredentialMountingEnabled() bool {
	return c.SecurityEnabled() && strings.TrimSpace(c.CredentialSecretPrefix) != ""
}

// CredentialSecretName returns the per-agent credential Secret name for the given
// prefix and agent. It is the single naming helper shared by the projection
// controller that writes the Secret and the mounting path that consumes it.
func CredentialSecretName(prefix, agentName string) string {
	return fmt.Sprintf("%s-%s", strings.TrimSpace(prefix), agentName)
}

// CredentialSecretName returns the name of the per-agent credential Secret for the
// given agent, using the configured prefix. It matches the name the projection
// controller writes, so the operator can mount it without coordination.
func (c Config) CredentialSecretName(agentName string) string {
	return CredentialSecretName(c.CredentialSecretPrefix, agentName)
}

// TokenEndpoint returns the agent-auth token endpoint derived from the issuer, or an
// empty string when no issuer is configured.
func (c Config) TokenEndpoint() string {
	issuer := strings.TrimRight(strings.TrimSpace(c.Issuer), "/")
	if issuer == "" {
		return ""
	}
	return issuer + "/oauth2/token"
}

// credentialMountDir is the directory into which the per-agent credential Secret is
// projected in agent pods. The client_secret is exposed as a file under this directory
// so the runtime can re-read it on rotation rather than relying on a static env value.
const credentialMountDir = "/var/run/aib"

// credentialSecretKey is the Secret data key holding the agent's client secret.
const credentialSecretKey = "client_secret"

// CredentialMountDir returns the directory under which the credential Secret is mounted.
func (c Config) CredentialMountDir() string {
	return credentialMountDir
}

// CredentialSecretKey returns the Secret data key holding the agent's client secret.
func (c Config) CredentialSecretKey() string {
	return credentialSecretKey
}

// CredentialSecretFilePath returns the absolute path of the mounted client_secret file
// that the runtime reads (and re-reads on rotation) to mint actor tokens.
func (c Config) CredentialSecretFilePath() string {
	return credentialMountDir + "/" + credentialSecretKey
}

// JWTEnabled reports whether the operator should emit jwt_authn providers on
// protected routes. It is true when either the agent issuer or the user issuer
// is configured. This is independent of IsOperational (which gates ext_authz):
// the jwt block is only rendered when at least one issuer is known.
func (c Config) JWTEnabled() bool {
	return strings.TrimSpace(c.Issuer) != "" || strings.TrimSpace(c.UserIssuer) != ""
}

// AgentJWKSURI returns the JWKS endpoint for the agent (actor) provider, derived
// from the agent-auth issuer. The broker publishes its signing keys at
// "<issuer>/oauth2/jwks.json". It returns an empty string when no issuer is set.
func (c Config) AgentJWKSURI() string {
	issuer := strings.TrimRight(strings.TrimSpace(c.Issuer), "/")
	if issuer == "" {
		return ""
	}
	return issuer + "/oauth2/jwks.json"
}

// UserJWKSURI returns the JWKS endpoint for the user (subject) provider. An
// explicit override (userAuth.jwksUri) takes precedence; otherwise it is derived
// from the user issuer using the standard OIDC realm path
// "<issuer>/protocol/openid-connect/certs" (Keycloak/OIDC). It returns an empty
// string when neither an override nor a user issuer is configured.
func (c Config) UserJWKSURI() string {
	if override := strings.TrimSpace(c.UserJWKSURIOverride); override != "" {
		return override
	}
	issuer := strings.TrimRight(strings.TrimSpace(c.UserIssuer), "/")
	if issuer == "" {
		return ""
	}
	return issuer + "/protocol/openid-connect/certs"
}

// ExtProcEnabled reports whether the operator should emit an EnvoyExtensionPolicy
// (ext_proc token exchange) on protected routes. It is true when ExtProcURL is
// configured. This is independent of IsOperational (which gates ext_authz): a
// deployment may enable token exchange without changing the ext_authz wiring.
func (c Config) ExtProcEnabled() bool {
	return strings.TrimSpace(c.ExtProcURL) != ""
}

// NetworkPolicyEnabled reports whether the operator should generate a
// NetworkPolicy for each protected workload. It requires security to be enabled
// (any enforcement hook) and the escape hatch not to be set. When true, direct
// workload-to-workload application traffic is denied so the Gateway cannot be
// bypassed.
func (c Config) NetworkPolicyEnabled() bool {
	return c.SecurityEnabled() && !c.NetworkPolicyDisabled
}

// NetworkPolicyEgressEnabled reports whether generated NetworkPolicies should
// also isolate egress. It requires base NetworkPolicy generation to be enabled
// and the explicit egress gate to be set, keeping existing ingress-only behavior
// as the default.
func (c Config) NetworkPolicyEgressEnabled() bool {
	return c.NetworkPolicyEnabled() && c.NetworkPolicyEgress
}

// GatewayNamespaceOrDefault returns the configured Envoy Gateway data-plane
// namespace, defaulting to "envoy-gateway-system" when unset. It is the ingress
// source allowed by generated NetworkPolicies.
func (c Config) GatewayNamespaceOrDefault() string {
	if ns := strings.TrimSpace(c.GatewayNamespace); ns != "" {
		return ns
	}
	return defaultGatewayNamespace
}

// OperatorNamespaceOrDefault returns the namespace the operator runs in,
// defaulting to "kaos-system" when neither SECURITY_OPERATOR_NAMESPACE nor
// POD_NAMESPACE is set. It is the ingress source allowed by generated
// NetworkPolicies so the operator can poll workload status endpoints.
func (c Config) OperatorNamespaceOrDefault() string {
	if ns := strings.TrimSpace(c.OperatorNamespace); ns != "" {
		return ns
	}
	return defaultOperatorNamespace
}

// GatewayRoutingEnabled reports whether the operator should inject gateway-routed
// endpoint URLs into agents so internal agent->MCP/ModelAPI/peer traffic flows
// through the gateway. It is off unless explicitly enabled. The actual gateway
// host is resolved separately (explicit GatewayHost or the Gateway status
// address); when no host can be resolved the controller falls back to direct
// Service URLs so connectivity is never silently broken.
func (c Config) GatewayRoutingEnabled() bool {
	return c.GatewayRouting
}

// ExtAuthzBackendRef parses the configured ext_authz host:port URL into the
// Kubernetes Service name, namespace, and port used to build the SecurityPolicy
// gRPC backendRef. The host is expected as a Service DNS name in the form
// "name[.namespace[.svc.cluster.local]]"; the namespace is empty when not present.
func (c Config) ExtAuthzBackendRef() (name, namespace string, port int, err error) {
	return parseServiceHostPort(c.ExtAuthzURL, "ext_authz")
}

// ExtProcBackendRef parses the configured ext_proc host:port URL into the
// Kubernetes Service name, namespace, and port used to build the
// EnvoyExtensionPolicy gRPC backendRef. The host is expected as a Service DNS
// name in the form "name[.namespace[.svc.cluster.local]]"; the namespace is empty
// when not present.
func (c Config) ExtProcBackendRef() (name, namespace string, port int, err error) {
	return parseServiceHostPort(c.ExtProcURL, "ext_proc")
}

// parseServiceHostPort parses a "host:port" Service DNS URL into name, namespace,
// and port. The label argument names the field in error messages. The host is
// expected as "name[.namespace[.svc.cluster.local]]"; namespace is empty when the
// host is a bare service name.
func parseServiceHostPort(rawURL, label string) (name, namespace string, port int, err error) {
	url := strings.TrimSpace(rawURL)
	if url == "" {
		return "", "", 0, fmt.Errorf("%s URL is empty", label)
	}

	host, portStr, found := strings.Cut(url, ":")
	if !found || host == "" || portStr == "" {
		return "", "", 0, fmt.Errorf("%s URL %q must be in host:port form", label, url)
	}
	port, err = strconv.Atoi(portStr)
	if err != nil || port <= 0 {
		return "", "", 0, fmt.Errorf("%s URL %q has an invalid port", label, url)
	}

	labels := strings.Split(host, ".")
	name = labels[0]
	if len(labels) > 1 {
		namespace = labels[1]
	}
	if name == "" {
		return "", "", 0, fmt.Errorf("%s URL %q has an empty service name", label, url)
	}
	return name, namespace, port, nil
}

// AuthorizationModelOrDefault returns the configured authorization model,
// defaulting to off (no projection) for unset or unrecognized values.
func (c Config) AuthorizationModelOrDefault() AuthorizationModel {
	return normalizeEnum(c.AuthorizationModel,
		[]AuthorizationModel{AuthorizationModelData, AuthorizationModelBroker, AuthorizationModelBoth},
		AuthorizationModelOff)
}

// AuthorizationEnabled reports whether any authorization model is selected.
func (c Config) AuthorizationEnabled() bool {
	return c.AuthorizationModelOrDefault() != AuthorizationModelOff
}

// EnforcementModeOrDefault returns the configured enforcement path, defaulting to
// OPA embedded in ext_proc.
func (c Config) EnforcementModeOrDefault() EnforcementMode {
	return normalizeEnum(c.EnforcementMode,
		[]EnforcementMode{EnforcementExtProc, EnforcementExtAuthz},
		EnforcementExtProc)
}

// VerificationModeOrDefault returns the configured verification mode. When unset
// or unrecognized it is derived from the agent issuer: verified when an issuer is
// configured, demo (header-trust) otherwise.
func (c Config) VerificationModeOrDefault() VerificationMode {
	def := VerificationDemo
	if strings.TrimSpace(c.Issuer) != "" {
		def = VerificationVerified
	}
	return normalizeEnum(c.VerificationMode,
		[]VerificationMode{VerificationDemo, VerificationVerified},
		def)
}

// PopulatorModeOrDefault returns the configured policy-data populator, defaulting
// to operator CRD projection.
func (c Config) PopulatorModeOrDefault() PopulatorMode {
	return normalizeEnum(c.PopulatorMode,
		[]PopulatorMode{PopulatorCRD, PopulatorBYOConfigMap, PopulatorOperatorRego, PopulatorExternal},
		PopulatorCRD)
}
