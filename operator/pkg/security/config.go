// Package security provides operator-wide configuration for resource-level
// authorization enforcement at the gateway. When configured, the operator
// attaches an external authorization (ext_authz) check to protected routes so
// that requests are allowed or denied based on the calling agent's granted
// permissions.
package security

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"strconv"
	"strings"
)

// Config holds operator-wide security configuration read from the environment.
// Security is enabled when the ext_authz access-check backend is configured.
type Config struct {
	// PDPEnabled enables the chart-managed OPA policy decision point. When true
	// and ExtAuthzURL is empty, ext_authz uses the kaos-pdp Service in the
	// operator namespace.
	PDPEnabled bool

	// IdentityProvider selects the single active agent identity issuer.
	IdentityProvider IdentityProvider

	// ServiceAccountAudience is the audience of projected agent tokens.
	ServiceAccountAudience string

	// ServiceAccountTokenExpirationSeconds controls projected token lifetime.
	ServiceAccountTokenExpirationSeconds int64

	// ServiceAccountTokenPath is the file exposed to the agent runtime.
	ServiceAccountTokenPath string

	// ServiceAccountIssuer and ServiceAccountJWKS are discovered from the
	// Kubernetes API server at operator startup.
	ServiceAccountIssuer string
	ServiceAccountJWKS   map[string]any

	// ExtAuthzURL is the host:port of the external authorization (ext_authz)
	// access-check gRPC backend override (agentAuth.extAuthzUrl). An empty value
	// uses the chart-managed PDP backend when PDPEnabled is true.
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
	// ext_authz applies) instead of directly to the workload Service. An
	// empty value lets the controller resolve the host from the Gateway resource's
	// status address.
	GatewayHost string

	// GatewayRouting enables injecting gateway-routed endpoint URLs into agents
	// (security.gatewayRouting.enabled). Default off so existing installs keep using
	// direct Service URLs; it is enabled together with NetworkPolicy to force the
	// gateway to be the only application path between workloads.
	GatewayRouting bool

	// StrictGatewayAPI turns on gateway-only strict traffic
	// (security.strictGatewayApi.enabled): NetworkPolicy isolation plus
	// gateway-routed URLs, independent of whether any authorization enforcement
	// hook is configured. It bundles the two because they are only useful
	// together — isolation without routing breaks connectivity, routing without
	// isolation is trivially bypassed. Default off; enforcement of the generated
	// NetworkPolicy still requires a CNI that enforces it (e.g. Calico).
	StrictGatewayAPI bool

	// AgentJWTVerificationMode selects how the agent (actor) JWT is trusted
	// (security.authorization.agentJwtVerification). Empty derives the mode from
	// the agent issuer: verified when an issuer is configured, skip (header-trust)
	// otherwise.
	AgentJWTVerificationMode AgentJWTVerificationMode

	// PolicyDataSource selects who authors the authorization policy data
	// (security.authorization.policyDataSource). Defaults to operator projection.
	PolicyDataSource PolicyDataSource

	// PolicyRegoOverride, when true, has the operator own only the policy.rego key
	// and never author the data key, so an admin supplies the grant data. It is an
	// orthogonal install-time option available in any PolicyDataSource.
	PolicyRegoOverride bool
}

// AgentJWTVerificationMode selects how the agent (actor) JWT is trusted by the
// policy.
type AgentJWTVerificationMode string

// IdentityProvider selects the active agent identity issuer.
type IdentityProvider string

const (
	IdentityProviderServiceAccount IdentityProvider = "serviceaccount"
	IdentityProviderOIDC           IdentityProvider = "oidc"
	IdentityProviderAIB            IdentityProvider = "aib"
)

const (
	// VerificationSkip trusts the actor header without signature verification;
	// used when no issuer is configured. Not for production.
	VerificationSkip AgentJWTVerificationMode = "skip"
	// VerificationVerified requires the actor JWT signature to be verified
	// against the injected JWKS.
	VerificationVerified AgentJWTVerificationMode = "verified"
)

// PolicyDataSource selects who authors the authorization policy data the operator
// enforces against.
type PolicyDataSource string

const (
	// PolicyDataAutomated projects the policy data from KAOS CRDs (default).
	PolicyDataAutomated PolicyDataSource = "automated"
	// PolicyDataManual points enforcement at an admin-authored data key the
	// operator does not project.
	PolicyDataManual PolicyDataSource = "manual"
)

const (
	defaultPDPServiceName                    = "kaos-pdp"
	defaultPDPPort                           = 9191
	defaultAgentTokenAudience                = "kaos-gateway"
	defaultAgentTokenExpirationSeconds int64 = 3600
	defaultAgentTokenPath                    = "/var/run/secrets/kaos-agent/token"

	envExtAuthzURL              = "SECURITY_AGENT_AUTH_EXT_AUTHZ_URL"
	envPDPEnabled               = "SECURITY_PDP_ENABLED"
	envIdentityProvider         = "SECURITY_AGENT_AUTH_IDENTITY_PROVIDER"
	envServiceAccountAudience   = "SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_AUDIENCE"
	envServiceAccountExpiration = "SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_EXPIRATION_SECONDS"
	envServiceAccountTokenPath  = "SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_TOKEN_PATH"
	envServiceAccountIssuer     = "SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_ISSUER"
	envServiceAccountJWKS       = "SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_JWKS"
	envIssuer                   = "SECURITY_AGENT_AUTH_ISSUER"
	envCredentialSecretPrefix   = "SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX"
	envUserIssuer               = "SECURITY_USER_AUTH_ISSUER"
	envUserAudience             = "SECURITY_USER_AUTH_AUDIENCE"
	envUserJWKSURI              = "SECURITY_USER_AUTH_JWKS_URI"
	envGatewayNamespace         = "SECURITY_GATEWAY_NAMESPACE"
	envOperatorNamespace        = "SECURITY_OPERATOR_NAMESPACE"
	envPodNamespace             = "POD_NAMESPACE"
	envNetworkPolicyDisabled    = "SECURITY_NETWORK_POLICY_DISABLED"
	envNetworkPolicyEgress      = "SECURITY_NETWORK_POLICY_EGRESS_ENABLED"
	envGatewayHost              = "SECURITY_GATEWAY_HOST"
	envGatewayRouting           = "SECURITY_GATEWAY_ROUTING_ENABLED"
	envStrictGatewayAPI         = "SECURITY_STRICT_GATEWAY_API_ENABLED"
	envAgentJWTVerification     = "SECURITY_AUTHORIZATION_AGENT_JWT_VERIFICATION"
	envPolicyDataSource         = "SECURITY_AUTHORIZATION_POLICY_DATA_SOURCE"
	envPolicyRegoOverride       = "SECURITY_AUTHORIZATION_POLICY_REGO_OVERRIDE"
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
	serviceAccountExpiration := defaultAgentTokenExpirationSeconds
	if parsed, err := strconv.ParseInt(strings.TrimSpace(os.Getenv(envServiceAccountExpiration)), 10, 64); err == nil && parsed > 0 {
		serviceAccountExpiration = parsed
	}
	serviceAccountAudience := strings.TrimSpace(os.Getenv(envServiceAccountAudience))
	if serviceAccountAudience == "" {
		serviceAccountAudience = defaultAgentTokenAudience
	}
	serviceAccountTokenPath := strings.TrimSpace(os.Getenv(envServiceAccountTokenPath))
	if serviceAccountTokenPath == "" {
		serviceAccountTokenPath = defaultAgentTokenPath
	}
	var serviceAccountJWKS map[string]any
	_ = json.Unmarshal([]byte(os.Getenv(envServiceAccountJWKS)), &serviceAccountJWKS)
	return Config{
		PDPEnabled:                           parseBoolEnv(envPDPEnabled),
		IdentityProvider:                     IdentityProvider(readEnumEnv(envIdentityProvider)),
		ServiceAccountAudience:               serviceAccountAudience,
		ServiceAccountTokenExpirationSeconds: serviceAccountExpiration,
		ServiceAccountTokenPath:              serviceAccountTokenPath,
		ServiceAccountIssuer:                 strings.TrimSpace(os.Getenv(envServiceAccountIssuer)),
		ServiceAccountJWKS:                   serviceAccountJWKS,
		ExtAuthzURL:                          os.Getenv(envExtAuthzURL),
		Issuer:                               os.Getenv(envIssuer),
		CredentialSecretPrefix:               os.Getenv(envCredentialSecretPrefix),
		UserIssuer:                           os.Getenv(envUserIssuer),
		UserAudience:                         os.Getenv(envUserAudience),
		UserJWKSURIOverride:                  os.Getenv(envUserJWKSURI),
		GatewayNamespace:                     os.Getenv(envGatewayNamespace),
		OperatorNamespace:                    operatorNamespace,
		NetworkPolicyDisabled:                parseBoolEnv(envNetworkPolicyDisabled),
		NetworkPolicyEgress:                  parseBoolEnv(envNetworkPolicyEgress),
		GatewayHost:                          os.Getenv(envGatewayHost),
		GatewayRouting:                       parseBoolEnv(envGatewayRouting),
		StrictGatewayAPI:                     parseBoolEnv(envStrictGatewayAPI),
		AgentJWTVerificationMode:             AgentJWTVerificationMode(readEnumEnv(envAgentJWTVerification)),
		PolicyDataSource:                     PolicyDataSource(readEnumEnv(envPolicyDataSource)),
		PolicyRegoOverride:                   parseBoolEnv(envPolicyRegoOverride),
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

// IsOperational reports whether ext_authz enforcement is enabled through the
// chart-managed PDP or an explicit backend override.
func (c Config) IsOperational() bool {
	return c.PDPEnabled || strings.TrimSpace(c.ExtAuthzURL) != ""
}

// SecurityEnabled reports whether gateway authorization enforcement is configured.
func (c Config) SecurityEnabled() bool {
	return c.IsOperational()
}

// CredentialMountingEnabled reports whether the operator should mount per-agent
// AIB credentials into agent pods. This requires security to be enabled and a
// credential Secret prefix to be configured.
func (c Config) CredentialMountingEnabled() bool {
	return c.IdentityProviderOrDefault() == IdentityProviderAIB && c.SecurityEnabled() && strings.TrimSpace(c.CredentialSecretPrefix) != ""
}

// IdentityProviderOrDefault returns the single configured issuer, preserving
// the existing AIB behavior when the setting is omitted or invalid.
func (c Config) IdentityProviderOrDefault() IdentityProvider {
	return normalizeEnum(c.IdentityProvider,
		[]IdentityProvider{IdentityProviderServiceAccount, IdentityProviderOIDC, IdentityProviderAIB},
		IdentityProviderAIB)
}

func (c Config) ServiceAccountIdentityEnabled() bool {
	return c.IdentityProviderOrDefault() == IdentityProviderServiceAccount
}

// AgentIssuer returns the issuer used by the gateway agent JWT provider.
func (c Config) AgentIssuer() string {
	if c.ServiceAccountIdentityEnabled() {
		return strings.TrimSpace(c.ServiceAccountIssuer)
	}
	return strings.TrimSpace(c.Issuer)
}

// AgentLocalJWKS returns the discovered cluster JWKS for ServiceAccount identity.
func (c Config) AgentLocalJWKS() map[string]any {
	if !c.ServiceAccountIdentityEnabled() {
		return nil
	}
	return c.ServiceAccountJWKS
}

// CredentialSecretName returns the per-agent credential Secret name for the given
// prefix and agent. It is the single naming helper shared by the projection
// controller that writes the Secret and the mounting path that consumes it.
func CredentialSecretName(prefix, agentName string) string {
	return fmt.Sprintf("%s-%s", strings.TrimSpace(prefix), agentName)
}

// AgentServiceAccountName returns the per-agent Kubernetes identity name.
func AgentServiceAccountName(agentName string) string {
	return "kaos-agent-" + agentName
}

func (c Config) ServiceAccountTokenMountDir() string {
	return path.Dir(c.ServiceAccountTokenPath)
}

func (c Config) ServiceAccountTokenFilename() string {
	return path.Base(c.ServiceAccountTokenPath)
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
	return c.AgentIssuer() != "" || strings.TrimSpace(c.UserIssuer) != ""
}

// AgentJWKSURI returns the JWKS endpoint for the agent (actor) provider, derived
// from the agent-auth issuer. The broker publishes its signing keys at
// "<issuer>/oauth2/jwks.json". It returns an empty string when no issuer is set.
func (c Config) AgentJWKSURI() string {
	if c.ServiceAccountIdentityEnabled() {
		return ""
	}
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

// NetworkPolicyEnabled reports whether the operator should generate a
// NetworkPolicy for each protected workload. It is true when strict gateway-only
// traffic is requested (independent of any enforcement hook), or when security is
// enabled (any enforcement hook) and the escape hatch is not set. When true,
// direct workload-to-workload application traffic is denied so the Gateway cannot
// be bypassed.
func (c Config) NetworkPolicyEnabled() bool {
	return c.StrictGatewayAPI || (c.SecurityEnabled() && !c.NetworkPolicyDisabled)
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
// through the gateway. It is on when gateway routing is explicitly enabled or when
// strict gateway-only traffic is requested (which bundles routing with isolation).
// The actual gateway host is resolved separately (explicit GatewayHost or the
// Gateway status address); when no host can be resolved the controller falls back
// to direct Service URLs so connectivity is never silently broken.
func (c Config) GatewayRoutingEnabled() bool {
	return c.GatewayRouting || c.StrictGatewayAPI
}

// ExtAuthzBackendRef parses the configured ext_authz host:port URL into the
// Kubernetes Service name, namespace, and port used to build the SecurityPolicy
// gRPC backendRef. The host is expected as a Service DNS name in the form
// "name[.namespace[.svc.cluster.local]]"; the namespace is empty when not present.
func (c Config) ExtAuthzBackendRef() (name, namespace string, port int, err error) {
	return parseServiceHostPort(c.ExtAuthzURLOrDefault(), "ext_authz")
}

// ExtAuthzURLOrDefault returns the explicit backend override when configured,
// otherwise the chart-managed PDP Service when PDP enforcement is enabled.
func (c Config) ExtAuthzURLOrDefault() string {
	if override := strings.TrimSpace(c.ExtAuthzURL); override != "" {
		return override
	}
	if !c.PDPEnabled {
		return ""
	}
	return fmt.Sprintf("%s.%s.svc:%d", defaultPDPServiceName, c.OperatorNamespaceOrDefault(), defaultPDPPort)
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

// ExtAuthzEnabled reports whether the operator should attach the ext_authz
// external-authorization check to protected routes. It remains default-off and
// requires a backend to be configured.
func (c Config) ExtAuthzEnabled() bool {
	return c.IsOperational()
}

// AuthzJWKSURI returns the agent (actor) JWKS endpoint the operator injects into
// the authorization policy data, but only in verified mode. In skip mode it
// returns an empty string, so no JWKS is injected and the policy denies actor
// tokens.
func (c Config) AuthzJWKSURI() string {
	if c.AgentJWTVerificationModeOrDefault() != VerificationVerified {
		return ""
	}
	return c.AgentJWKSURI()
}

// AgentJWTVerificationModeOrDefault returns the configured agent JWT
// verification mode, deriving the default from the issuer: verified when an
// issuer is configured, skip otherwise.
func (c Config) AgentJWTVerificationModeOrDefault() AgentJWTVerificationMode {
	def := VerificationSkip
	if c.AgentIssuer() != "" {
		def = VerificationVerified
	}
	return normalizeEnum(c.AgentJWTVerificationMode,
		[]AgentJWTVerificationMode{VerificationSkip, VerificationVerified},
		def)
}

// PolicyDataSourceOrDefault returns the configured policy-data source, defaulting
// to operator projection.
func (c Config) PolicyDataSourceOrDefault() PolicyDataSource {
	return normalizeEnum(c.PolicyDataSource,
		[]PolicyDataSource{PolicyDataAutomated, PolicyDataManual},
		PolicyDataAutomated)
}
