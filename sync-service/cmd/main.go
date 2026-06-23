// Command kaos-sync projects KAOS Agent/MCPServer/ModelAPI resources into the
// Agentic Identity Broker and provisions per-agent credential Secrets. It is a
// standalone controller-runtime manager: the framework supplies the watch,
// cache, leader election, periodic resync, requeue/backoff and health probes,
// leaving only the projection, AIB admin calls and Secret provisioning as code.
//
// Configuration is environment-only (mirroring the Python service): a tagged
// Settings struct is populated by envconfig, so there is no flag plumbing.
package main

import (
	"os"
	"strings"
	"time"

	"github.com/sethvargo/go-envconfig"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	"github.com/axsaucedo/kaos/sync-service/internal/aib"
	syncctrl "github.com/axsaucedo/kaos/sync-service/internal/sync"
)

// Settings is the full runtime configuration, sourced from the environment.
type Settings struct {
	AIBAdminURL     string        `env:"AIB_ADMIN_URL, default=http://localhost:14000/api"`
	AIBPrincipal    string        `env:"AIB_PRINCIPAL, default=kaos-sync"`
	PrincipalHeader string        `env:"AIB_PRINCIPAL_HEADER, default=X-Remote-User"`
	Namespaces      string        `env:"KAOS_SYNC_NAMESPACES"`
	SecretPrefix    string        `env:"KAOS_SYNC_CREDENTIAL_SECRET_PREFIX, default=kaos-aib"`
	Resync          time.Duration `env:"KAOS_SYNC_RECONCILE_INTERVAL, default=30s"`
	RequestTimeout  time.Duration `env:"KAOS_SYNC_REQUEST_TIMEOUT, default=10s"`
	Prune           bool          `env:"KAOS_SYNC_PRUNE_ENABLED, default=true"`
	LeaderElect     bool          `env:"KAOS_SYNC_LEADER_ELECTION_ENABLED, default=true"`
	LeaderNamespace string        `env:"POD_NAMESPACE, default=kaos-system"`
	ProbeAddr       string        `env:"KAOS_SYNC_HEALTH_PROBE_ADDRESS, default=:8081"`
	MetricsAddr     string        `env:"KAOS_SYNC_METRICS_ADDRESS, default=:8080"`
}

func main() {
	ctx := ctrl.SetupSignalHandler()
	ctrl.SetLogger(zap.New(zap.UseDevMode(false)))
	logger := ctrl.Log.WithName("setup")

	var cfg Settings
	if err := envconfig.Process(ctx, &cfg); err != nil {
		logger.Error(err, "loading configuration")
		os.Exit(1)
	}

	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		logger.Error(err, "building scheme")
		os.Exit(1)
	}

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme:                  scheme,
		Metrics:                 metricsserver.Options{BindAddress: cfg.MetricsAddr},
		HealthProbeBindAddress:  cfg.ProbeAddr,
		LeaderElection:          cfg.LeaderElect,
		LeaderElectionID:        "kaos-sync-leader",
		LeaderElectionNamespace: cfg.LeaderNamespace,
		Cache:                   cacheOptions(cfg.Namespaces, cfg.Resync),
	})
	if err != nil {
		logger.Error(err, "creating manager")
		os.Exit(1)
	}

	admin := aib.New(cfg.AIBAdminURL, cfg.AIBPrincipal, cfg.PrincipalHeader, cfg.RequestTimeout)
	reconciler := &syncctrl.Reconciler{
		Client:       mgr.GetClient(),
		AIB:          admin,
		Namespaces:   splitCSV(cfg.Namespaces),
		SecretPrefix: cfg.SecretPrefix,
		Prune:        cfg.Prune,
	}
	if err := reconciler.SetupWithManager(mgr); err != nil {
		logger.Error(err, "registering controller")
		os.Exit(1)
	}

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		logger.Error(err, "adding health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		logger.Error(err, "adding ready check")
		os.Exit(1)
	}

	logger.Info("starting kaos-sync",
		"aibAdminURL", cfg.AIBAdminURL, "namespaces", cfg.Namespaces, "prune", cfg.Prune,
		"leaderElect", cfg.LeaderElect, "resync", cfg.Resync)
	if err := mgr.Start(ctx); err != nil {
		logger.Error(err, "manager exited")
		os.Exit(1)
	}
}

// cacheOptions builds the manager's cache options: scope the watched namespaces
// (empty = cluster-wide) and set the safety-net resync period.
func cacheOptions(namespacesCSV string, resync time.Duration) cache.Options {
	opts := cache.Options{SyncPeriod: &resync}
	namespaces := splitCSV(namespacesCSV)
	if len(namespaces) > 0 {
		byNS := map[string]cache.Config{}
		for _, ns := range namespaces {
			byNS[ns] = cache.Config{}
		}
		opts.DefaultNamespaces = byNS
	}
	return opts
}

func splitCSV(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}
