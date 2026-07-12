package main

import (
	"context"
	"encoding/json"
	"flag"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	// Import all Kubernetes client auth plugins (e.g. Azure, GCP, OIDC, etc.)
	_ "k8s.io/client-go/plugin/pkg/client/auth"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/controllers"
	"github.com/axsaucedo/kaos/operator/internal/aib"
	"github.com/axsaucedo/kaos/operator/internal/authz"
	"github.com/axsaucedo/kaos/operator/internal/authz/adapters"
	"github.com/axsaucedo/kaos/operator/internal/authz/dcr"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

// RBAC for leader election - these annotations ensure controller-gen includes
// leases and events permissions in the generated role.yaml.
// DO NOT REMOVE - required for leader election to work properly.
//+kubebuilder:rbac:groups=coordination.k8s.io,resources=leases,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=events,verbs=create;patch
//+kubebuilder:rbac:groups=gateway.networking.k8s.io,resources=httproutes,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=gateway.networking.k8s.io,resources=gateways,verbs=get;list;watch
//+kubebuilder:rbac:groups=gateway.networking.k8s.io,resources=referencegrants,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=gateway.envoyproxy.io,resources=securitypolicies,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=networking.k8s.io,resources=networkpolicies,verbs=get;list;watch;create;update;patch;delete

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(kaosv1alpha1.AddToScheme(scheme))
	utilruntime.Must(gatewayv1.Install(scheme))
}

func main() {
	var metricsAddr string
	var enableLeaderElection bool
	var probeAddr string

	flag.StringVar(&metricsAddr, "metrics-bind-address", ":8080", "The address the metric endpoint binds to.")
	flag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "The address the probe endpoint binds to.")
	flag.BoolVar(&enableLeaderElection, "leader-elect", false,
		"Enable leader election for controller manager. "+
			"Enabling this will ensure there is only one active controller manager.")

	opts := zap.Options{
		Development: true,
	}
	opts.BindFlags(flag.CommandLine)
	flag.Parse()

	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	restConfig := ctrl.GetConfigOrDie()
	if security.GetConfig().ServiceAccountIdentityEnabled() {
		issuerKeys, discoveryErr := authz.DiscoverServiceAccountIssuer(context.Background(), restConfig)
		if discoveryErr != nil {
			setupLog.Error(discoveryErr, "unable to discover Kubernetes ServiceAccount issuer")
			os.Exit(1)
		}
		jwks, marshalErr := json.Marshal(issuerKeys.JWKS)
		if marshalErr != nil {
			setupLog.Error(marshalErr, "unable to encode Kubernetes ServiceAccount JWKS")
			os.Exit(1)
		}
		_ = os.Setenv("SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_ISSUER", issuerKeys.Issuer)
		_ = os.Setenv("SECURITY_AGENT_AUTH_SERVICE_ACCOUNT_JWKS", string(jwks))
	}

	mgr, err := ctrl.NewManager(restConfig, ctrl.Options{
		Scheme:                 scheme,
		HealthProbeBindAddress: probeAddr,
		LeaderElection:         enableLeaderElection,
		LeaderElectionID:       "kaos-operator.kaos.tools",
	})
	if err != nil {
		setupLog.Error(err, "unable to start manager")
		os.Exit(1)
	}

	// Setup controllers
	if err = (&controllers.ModelAPIReconciler{
		Client: mgr.GetClient(),
		Log:    setupLog,
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "ModelAPI")
		os.Exit(1)
	}

	if err = (&controllers.MCPServerReconciler{
		Client:          mgr.GetClient(),
		Log:             setupLog,
		Scheme:          mgr.GetScheme(),
		SystemNamespace: getEnvWithDefault("SYSTEM_NAMESPACE", "kaos"),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "MCPServer")
		os.Exit(1)
	}

	if err = (&controllers.MemoryStoreReconciler{
		Client: mgr.GetClient(),
		Log:    setupLog,
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "MemoryStore")
		os.Exit(1)
	}

	if err = (&controllers.AgentReconciler{
		Client: mgr.GetClient(),
		Log:    setupLog,
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "Agent")
		os.Exit(1)
	}

	// Identity provisioning and policy compilation are independent projection
	// sinks. The controller runs whenever either sink is configured.
	cfg := security.GetConfig()
	policyName := os.Getenv("AUTHZ_POLICY_CONFIGMAP_NAME")
	policyNamespace := os.Getenv("AUTHZ_POLICY_CONFIGMAP_NAMESPACE")
	adminURL := os.Getenv("AIB_ADMIN_URL")
	projectionNamespaces := splitCSV(os.Getenv("AUTHZ_PROJECTION_NAMESPACES"))
	var projectors []controllers.PolicyProjector
	if adminURL != "" && cfg.IdentityProviderOrDefault() == security.IdentityProviderAIB {
		projectors = append(projectors, &adapters.BrokerProjector{
			Client: mgr.GetClient(),
			Scheme: mgr.GetScheme(),
			AIB: aib.New(
				adminURL,
				getEnvWithDefault("AIB_PRINCIPAL", "kaos-operator"),
				getEnvWithDefault("AIB_PRINCIPAL_HEADER", "X-Remote-User"),
				getDurationWithDefault("AIB_REQUEST_TIMEOUT", 10*time.Second),
			),
			SecretPrefix: getEnvWithDefault("SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX", "kaos-aib"),
			Prune:        getBoolWithDefault("AUTHZ_PROJECTION_PRUNE_ENABLED", true),
			HTTPClient:   &http.Client{Timeout: 5 * time.Second},
			Issuer:       cfg.AgentIssuer(),
			Namespaces:   projectionNamespaces,
		})
	}
	if cfg.IdentityProviderOrDefault() == security.IdentityProviderOIDC && cfg.AgentIssuer() != "" && cfg.OIDCRegistrationInitialAccessToken != "" {
		httpClient := &http.Client{Timeout: 10 * time.Second}
		projectors = append(projectors, &adapters.OIDCProjector{
			Client: mgr.GetClient(),
			Scheme: mgr.GetScheme(),
			DCR: &dcr.Client{
				Issuer:             cfg.AgentIssuer(),
				InitialAccessToken: cfg.OIDCRegistrationInitialAccessToken,
				HTTPClient:         httpClient,
			},
			SecretPrefix: cfg.CredentialSecretPrefixOrDefault(),
			Prune:        getBoolWithDefault("AUTHZ_PROJECTION_PRUNE_ENABLED", true),
			Namespaces:   projectionNamespaces,
		})
	}
	if policyName != "" && policyNamespace != "" {
		policyDataSource := cfg.PolicyDataSourceOrDefault()
		projectors = append(projectors, &adapters.AuthzPolicyProjector{
			Client:             mgr.GetClient(),
			Name:               policyName,
			Namespace:          policyNamespace,
			JWKSURI:            cfg.AuthzJWKSURI(),
			Issuer:             cfg.AgentIssuer(),
			UserIssuer:         cfg.UserIssuer,
			UserAudience:       cfg.UserAudience,
			UserJWKSURI:        cfg.UserJWKSURI(),
			StaticJWKS:         cfg.AgentLocalJWKS(),
			MapServiceAccounts: cfg.ServiceAccountIdentityEnabled(),
			WriteGrantData:     policyDataSource == security.PolicyDataAutomated && !cfg.PolicyRegoOverride,
			Disabled:           policyDataSource == security.PolicyDataManual && !cfg.PolicyRegoOverride,
		})
	}
	if len(projectors) > 0 {
		if err = (&controllers.AuthzProjectionReconciler{
			Client:     mgr.GetClient(),
			Scheme:     mgr.GetScheme(),
			Namespaces: projectionNamespaces,
			Projectors: projectors,
			UserIssuer: cfg.UserIssuer,
			Recorder:   mgr.GetEventRecorderFor("kaos-authz-projection"),
		}).SetupWithManager(mgr); err != nil {
			setupLog.Error(err, "unable to create controller", "controller", "AuthzProjection")
			os.Exit(1)
		}
	}

	// Webhooks not implemented yet in this version
	// TODO: Add webhook setup when webhooks are needed

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	setupLog.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		setupLog.Error(err, "problem running manager")
		os.Exit(1)
	}
}

func getEnvWithDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getBoolWithDefault(key string, defaultValue bool) bool {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return defaultValue
	}
	parsed, err := strconv.ParseBool(v)
	if err != nil {
		return defaultValue
	}
	return parsed
}

func getDurationWithDefault(key string, defaultValue time.Duration) time.Duration {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return defaultValue
	}
	parsed, err := time.ParseDuration(v)
	if err != nil {
		return defaultValue
	}
	return parsed
}

// splitCSV splits a comma-separated list into trimmed, non-empty entries.
func splitCSV(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}
