package main

import (
	"flag"
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
//+kubebuilder:rbac:groups=gateway.envoyproxy.io,resources=securitypolicies,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=gateway.envoyproxy.io,resources=envoyextensionpolicies,verbs=get;list;watch;create;update;patch;delete
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

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
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

	if err = (&controllers.AgentReconciler{
		Client: mgr.GetClient(),
		Log:    setupLog,
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "Agent")
		os.Exit(1)
	}

	// The AIB projection controller is the operator's only caller of the broker
	// admin API and the only minter of per-agent credential Secrets. It runs
	// independently of the workload controllers so a broker outage never stalls
	// workload reconciliation. It is enabled by configuring the broker admin URL;
	// when unset the operator runs without any projection (unchanged behaviour).
	if aibAdminURL := os.Getenv("AIB_ADMIN_URL"); aibAdminURL != "" {
		admin := aib.New(
			aibAdminURL,
			getEnvWithDefault("AIB_PRINCIPAL", "kaos-operator"),
			getEnvWithDefault("AIB_PRINCIPAL_HEADER", "X-Remote-User"),
			getDurationWithDefault("AIB_REQUEST_TIMEOUT", 10*time.Second),
		)
		if err = (&controllers.AIBProjectionReconciler{
			Client:       mgr.GetClient(),
			AIB:          admin,
			Namespaces:   splitCSV(os.Getenv("AIB_PROJECTION_NAMESPACES")),
			SecretPrefix: getEnvWithDefault("SECURITY_AGENT_AUTH_CREDENTIAL_SECRET_PREFIX", "kaos-aib"),
			Prune:        getBoolWithDefault("AIB_PROJECTION_PRUNE_ENABLED", true),
		}).SetupWithManager(mgr); err != nil {
			setupLog.Error(err, "unable to create controller", "controller", "AIBProjection")
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
