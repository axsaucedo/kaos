package controllers

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/go-logr/logr"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/utils/ptr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
	"github.com/axsaucedo/kaos/operator/pkg/security"
	"github.com/axsaucedo/kaos/operator/pkg/util"
)

const agentFinalizerName = "kaos.tools/agent-finalizer"
const exchangeReflectionName = "kaos-token-exchange-reflection"

// AgentReconciler reconciles an Agent object
type AgentReconciler struct {
	client.Client
	Log    logr.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=kaos.tools,resources=agents,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=kaos.tools,resources=agents/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=kaos.tools,resources=agents/finalizers,verbs=update
//+kubebuilder:rbac:groups=kaos.tools,resources=modelapis,verbs=get;list;watch
//+kubebuilder:rbac:groups=kaos.tools,resources=mcpservers,verbs=get;list;watch
//+kubebuilder:rbac:groups=kaos.tools,resources=memorystores,verbs=get;list;watch
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=serviceaccounts,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *AgentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	agent := &kaosv1alpha1.Agent{}
	if err := r.Get(ctx, req.NamespacedName, agent); err != nil {
		// Ignore not-found errors (resource was deleted)
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Handle deletion with finalizer
	if agent.ObjectMeta.DeletionTimestamp != nil {
		if controllerutil.ContainsFinalizer(agent, agentFinalizerName) {
			log.Info("Deleting Agent", "name", agent.Name)
			controllerutil.RemoveFinalizer(agent, agentFinalizerName)
			if err := r.Update(ctx, agent); err != nil {
				log.Error(err, "failed to remove finalizer")
				return ctrl.Result{}, err
			}
		}
		return ctrl.Result{}, nil
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(agent, agentFinalizerName) {
		controllerutil.AddFinalizer(agent, agentFinalizerName)
		if err := r.Update(ctx, agent); err != nil {
			log.Error(err, "failed to add finalizer")
			return ctrl.Result{}, err
		}
		// Requeue to continue with fresh object after finalizer is added
		return ctrl.Result{Requeue: true}, nil
	}

	// Set initial status
	if agent.Status.Phase == "" {
		agent.Status.Phase = "Pending"
		agent.Status.Ready = false
		agent.Status.LinkedResources = make(map[string]string)
		if err := r.Status().Update(ctx, agent); err != nil {
			log.Error(err, "failed to update status")
			return ctrl.Result{}, err
		}
		// Requeue to continue with fresh object after status is set
		return ctrl.Result{Requeue: true}, nil
	}

	// Validate telemetry config
	var componentTelemetry *kaosv1alpha1.TelemetryConfig
	if agent.Spec.Config != nil {
		componentTelemetry = agent.Spec.Config.Telemetry
	}
	telemetryConfig := util.MergeTelemetryConfig(componentTelemetry)
	if !util.IsTelemetryConfigValid(telemetryConfig) {
		log.Info("WARNING: telemetry.enabled=true but endpoint is empty; telemetry will not function", "agent", agent.Name)
	}

	// Validate autonomous configuration (goal is required to activate)
	// No validation needed — autonomous section without a goal is simply a no-op

	// Resolve ModelAPI reference
	modelapi := &kaosv1alpha1.ModelAPI{}
	err := r.Get(ctx, types.NamespacedName{Name: agent.Spec.ModelAPI, Namespace: agent.Namespace}, modelapi)
	if err != nil {
		if apierrors.IsNotFound(err) {
			// ModelAPI doesn't exist (may have been deleted) - wait for it
			log.Info("ModelAPI not found, waiting", "modelAPI", agent.Spec.ModelAPI)
			agent.Status.Phase = "Waiting"
			agent.Status.Message = fmt.Sprintf("ModelAPI %s not found", agent.Spec.ModelAPI)
			if err := r.Status().Update(ctx, agent); err != nil {
				log.Error(err, "failed to update status")
			}
			return ctrl.Result{RequeueAfter: time.Second * 5}, nil
		}
		// Other errors - log and retry
		log.Error(err, "unable to fetch ModelAPI", "modelAPI", agent.Spec.ModelAPI)
		agent.Status.Phase = "Failed"
		agent.Status.Message = fmt.Sprintf("Failed to resolve ModelAPI: %v", err)
		if err := r.Status().Update(ctx, agent); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{}, err
	}

	// Check if we should wait for dependencies (default true)
	waitForDeps := agent.Spec.WaitForDependencies == nil || *agent.Spec.WaitForDependencies

	if !modelapi.Status.Ready && waitForDeps {
		log.Info("ModelAPI not ready, waiting", "modelAPI", agent.Spec.ModelAPI)
		agent.Status.Phase = "Waiting"
		agent.Status.Message = "ModelAPI is not ready"
		if err := r.Status().Update(ctx, agent); err != nil {
			log.Error(err, "failed to update status")
		}
		return ctrl.Result{}, nil
	}

	// Validate that agent's model is supported by the ModelAPI
	if err := r.validateAgentModel(agent, modelapi); err != nil {
		log.Error(err, "model validation failed")
		agent.Status.Phase = "Failed"
		agent.Status.Message = err.Error()
		if statusErr := r.Status().Update(ctx, agent); statusErr != nil {
			log.Error(statusErr, "failed to update status")
		}
		return ctrl.Result{}, nil
	}

	// Resolve MCPServer references
	mcpServers := make(map[string]string)
	for _, mcpName := range agent.Spec.MCPServers {
		mcp := &kaosv1alpha1.MCPServer{}
		err := r.Get(ctx, types.NamespacedName{Name: mcpName, Namespace: agent.Namespace}, mcp)
		if err != nil {
			if apierrors.IsNotFound(err) {
				// MCPServer doesn't exist (may have been deleted) - wait for it
				log.Info("MCPServer not found, waiting", "mcpserver", mcpName)
				agent.Status.Phase = "Waiting"
				agent.Status.Message = fmt.Sprintf("MCPServer %s not found", mcpName)
				if err := r.Status().Update(ctx, agent); err != nil {
					log.Error(err, "failed to update status")
				}
				return ctrl.Result{RequeueAfter: time.Second * 5}, nil
			}
			// Other errors - log and retry
			log.Error(err, "unable to fetch MCPServer", "mcpserver", mcpName)
			agent.Status.Phase = "Failed"
			agent.Status.Message = fmt.Sprintf("Failed to resolve MCPServer %s: %v", mcpName, err)
			if err := r.Status().Update(ctx, agent); err != nil {
				return ctrl.Result{}, err
			}
			return ctrl.Result{}, err
		}

		if !mcp.Status.Ready && waitForDeps {
			log.Info("MCPServer not ready, waiting", "mcpserver", mcpName)
			agent.Status.Phase = "Waiting"
			agent.Status.Message = fmt.Sprintf("MCPServer %s is not ready", mcpName)
			if err := r.Status().Update(ctx, agent); err != nil {
				log.Error(err, "failed to update status")
			}
			return ctrl.Result{}, nil
		}

		mcpServers[mcpName] = mcp.Status.Endpoint
	}

	// Resolve peer agent endpoints
	peerAgents := make(map[string]string)
	if agent.Spec.AgentNetwork != nil {
		for _, peerName := range agent.Spec.AgentNetwork.Access {
			peerAgent := &kaosv1alpha1.Agent{}
			err := r.Get(ctx, types.NamespacedName{Name: peerName, Namespace: agent.Namespace}, peerAgent)
			if err != nil {
				log.Info("peer agent not found yet", "peer", peerName)
				continue
			}

			if peerAgent.Status.Endpoint != "" {
				peerAgents[peerName] = peerAgent.Status.Endpoint
				log.Info("found peer agent endpoint", "peer", peerName, "endpoint", peerAgent.Status.Endpoint)
			}
		}
	}

	// Resolve the bound MemoryStore (long-term tier). Memory is an augmentation,
	// not a tier-1 dependency at runtime: an unresolved or not-ready store degrades
	// an already-running agent to short-term only rather than tearing it down. The
	// one exception is the agent's *initial* creation, which is gated on memory
	// availability (parity with ModelAPI/MCPServer) so an agent never starts up
	// degraded — see the gating block below.
	//
	// Resolution states (invariant: memoryEndpoint is non-empty iff the store is
	// Ready, so "degraded" uniformly means "fall back to short-term only"):
	//
	//   1. no memory block             -> endpoint "", not degraded, no memory
	//   2. effective type local        -> endpoint "", not degraded, short-term only
	//   3. remote, store NotFound      -> endpoint "", degraded (gates first creation)
	//   4. remote, store not Ready     -> endpoint "", degraded (gates first creation)
	//   5. remote, store Ready         -> endpoint set, not degraded, full memory
	//   6. remote, transient Get error -> requeue (return err)
	//
	// MemoryDegraded is always reconciled to reflect the current state (including
	// cleared to False on states 1/2/5), so a store recovering or an agent moving
	// remote->local clears a stale condition.
	memoryEndpoint := ""
	memoryDegraded := false
	memoryDegradedMsg := ""
	memoryStoreName := ""
	var resolvedMemoryStore *kaosv1alpha1.MemoryStore
	if agent.Spec.Config != nil && agent.Spec.Config.Memory != nil {
		mem := agent.Spec.Config.Memory
		effectiveType := mem.Type
		if effectiveType == "" {
			if mem.MemoryStore != "" {
				effectiveType = "remote"
			} else {
				effectiveType = "local"
			}
		}
		if effectiveType == "remote" && mem.MemoryStore != "" {
			memoryStoreName = mem.MemoryStore
			store := &kaosv1alpha1.MemoryStore{}
			err := r.Get(ctx, types.NamespacedName{Name: mem.MemoryStore, Namespace: agent.Namespace}, store)
			if err != nil {
				if apierrors.IsNotFound(err) {
					memoryDegraded = true
					memoryDegradedMsg = fmt.Sprintf("MemoryStore %s not found", mem.MemoryStore)
				} else {
					log.Error(err, "failed to resolve MemoryStore", "memorystore", mem.MemoryStore)
					return ctrl.Result{}, err
				}
			} else if !store.Status.Ready {
				resolvedMemoryStore = store
				// Store exists but is warming up. Withhold the endpoint so the
				// runtime falls back to short-term rather than dialling a service
				// that is not yet serving.
				memoryDegraded = true
				memoryDegradedMsg = fmt.Sprintf("MemoryStore %s is not ready", mem.MemoryStore)
			} else {
				resolvedMemoryStore = store
				memoryEndpoint = store.Status.Endpoint
			}
		}
	}

	// Gate only the agent's *initial* creation on memory availability. If the
	// bound store is unavailable (missing or warming up) and the agent has no
	// Deployment yet, wait rather than starting up degraded — mirroring the
	// ModelAPI/MCPServer dependency gate. An already-running agent is never gated
	// or torn down when its store later disappears; it degrades to short-term
	// only. The MemoryStore watch requeues the agent once the store turns Ready.
	if memoryDegraded && waitForDeps {
		exists, err := r.agentDeploymentExists(ctx, agent)
		if err != nil {
			log.Error(err, "failed to check existing Deployment for memory gating")
			return ctrl.Result{}, err
		}
		if !exists {
			log.Info("MemoryStore not available and agent not yet created, waiting",
				"memorystore", memoryStoreName)
			agent.Status.Phase = "Waiting"
			agent.Status.Message = memoryDegradedMsg
			if err := r.Status().Update(ctx, agent); err != nil {
				log.Error(err, "failed to update status")
			}
			return ctrl.Result{RequeueAfter: time.Second * 5}, nil
		}
	}

	// When gateway routing is enabled, repoint internal endpoints at the gateway so
	// agent->ModelAPI/MCP/peer traffic traverses jwt_authn/ext_authz rather
	// than reaching the workload Service directly (which NetworkPolicy denies).
	r.applyGatewayRouting(ctx, agent, modelapi, mcpServers, peerAgents, memoryStoreName, &memoryEndpoint, log)
	tokenExchangeConfig, err := r.tokenExchangeConfig(ctx, agent)
	if err != nil {
		return ctrl.Result{}, err
	}
	if err := r.reconcileAgentServiceAccount(ctx, agent); err != nil {
		return ctrl.Result{}, err
	}
	var memoryConfig *kaosv1alpha1.MemoryConfig
	if agent.Spec.Config != nil {
		memoryConfig = agent.Spec.Config.Memory
	}
	memoryScope := resolveMemoryScope(memoryConfig, resolvedMemoryStore)

	// Create or update Deployment
	deployment := &appsv1.Deployment{}
	deploymentName := fmt.Sprintf("agent-%s", agent.Name)
	err = r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: agent.Namespace}, deployment)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Deployment
		deployment, err = r.constructDeployment(agent, modelapi, mcpServers, peerAgents, memoryEndpoint, memoryScope, tokenExchangeConfig)
		if err != nil {
			log.Error(err, "failed to construct Deployment")
			agent.Status.Phase = "Failed"
			agent.Status.Message = fmt.Sprintf("Failed to construct Deployment: %v", err)
			if statusErr := r.Status().Update(ctx, agent); statusErr != nil {
				return ctrl.Result{}, statusErr
			}
			return ctrl.Result{}, err
		}
		if err := controllerutil.SetControllerReference(agent, deployment, r.Scheme); err != nil {
			log.Error(err, "failed to set controller reference")
			return ctrl.Result{}, err
		}

		log.Info("Creating Deployment", "name", deployment.Name)
		if err := r.Create(ctx, deployment); err != nil {
			log.Error(err, "failed to create Deployment")
			agent.Status.Phase = "Failed"
			agent.Status.Message = fmt.Sprintf("Failed to create Deployment: %v", err)
			if statusErr := r.Status().Update(ctx, agent); statusErr != nil {
				return ctrl.Result{}, statusErr
			}
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "failed to get Deployment")
		return ctrl.Result{}, err
	} else {
		// Deployment exists - check if spec has changed using hash annotation
		desiredDeployment, err := r.constructDeployment(agent, modelapi, mcpServers, peerAgents, memoryEndpoint, memoryScope, tokenExchangeConfig)
		if err != nil {
			log.Error(err, "failed to construct Deployment for comparison")
			return ctrl.Result{}, err
		}
		currentHash := ""
		if deployment.Spec.Template.Annotations != nil {
			currentHash = deployment.Spec.Template.Annotations[util.PodSpecHashAnnotation]
		}
		desiredHash := ""
		if desiredDeployment.Spec.Template.Annotations != nil {
			desiredHash = desiredDeployment.Spec.Template.Annotations[util.PodSpecHashAnnotation]
		}

		if currentHash != desiredHash {
			log.Info("Updating Deployment due to spec change", "name", deployment.Name,
				"currentHash", currentHash, "desiredHash", desiredHash)
			// Update the deployment spec to trigger rolling update
			deployment.Spec.Template = desiredDeployment.Spec.Template
			if err := r.Update(ctx, deployment); err != nil {
				log.Error(err, "failed to update Deployment")
				return ctrl.Result{}, err
			}
		}
	}

	// Create or update A2A Service (if expose is enabled - default true)
	exposeEnabled := agent.Spec.AgentNetwork == nil || agent.Spec.AgentNetwork.Expose == nil || *agent.Spec.AgentNetwork.Expose
	if exposeEnabled {
		service := &corev1.Service{}
		serviceName := fmt.Sprintf("agent-%s", agent.Name)
		err = r.Get(ctx, types.NamespacedName{Name: serviceName, Namespace: agent.Namespace}, service)

		if err != nil && apierrors.IsNotFound(err) {
			service = r.constructService(agent)
			if err := controllerutil.SetControllerReference(agent, service, r.Scheme); err != nil {
				log.Error(err, "failed to set controller reference")
				return ctrl.Result{}, err
			}

			log.Info("Creating Service", "name", service.Name)
			if err := r.Create(ctx, service); err != nil {
				log.Error(err, "failed to create Service")
				agent.Status.Phase = "Failed"
				agent.Status.Message = fmt.Sprintf("Failed to create Service: %v", err)
				if statusErr := r.Status().Update(ctx, agent); statusErr != nil {
					return ctrl.Result{}, statusErr
				}
				return ctrl.Result{}, err
			}
		} else if err != nil {
			log.Error(err, "failed to get Service")
			return ctrl.Result{}, err
		}

		// Set endpoint for A2A (base URL only - clients append paths like /.well-known/agent.json)
		agent.Status.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local:8000", serviceName, agent.Namespace)

		// Create HTTPRoute if Gateway API is enabled
		timeout := ""
		if agent.Spec.GatewayRoute != nil && agent.Spec.GatewayRoute.Timeout != "" {
			timeout = agent.Spec.GatewayRoute.Timeout
		}
		if err := gateway.ReconcileHTTPRoute(ctx, r.Client, r.Scheme, agent, gateway.HTTPRouteParams{
			ResourceType: gateway.ResourceTypeAgent,
			ResourceName: agent.Name,
			Namespace:    agent.Namespace,
			ServiceName:  serviceName,
			ServicePort:  8000,
			Labels:       map[string]string{"app": "agent", "agent": agent.Name},
			Timeout:      timeout,
		}, log); err != nil {
			log.Error(err, "failed to reconcile HTTPRoute")
		}

		if secCfg := security.GetConfig(); secCfg.SecurityEnabled() {
			routeName := gateway.HTTPRouteName(gateway.ResourceTypeAgent, agent.Name)
			policyParams := security.PolicyParams{
				Name:      routeName,
				Namespace: agent.Namespace,
				RouteName: routeName,
				Labels:    map[string]string{"app": "agent", "agent": agent.Name},
			}
			if err := security.ReconcileSecurityPolicy(ctx, r.Client, r.Scheme, agent, policyParams, secCfg, log); err != nil {
				log.Error(err, "failed to reconcile SecurityPolicy")
			}
			if err := security.ReconcileNetworkPolicy(ctx, r.Client, r.Scheme, agent, security.NetworkPolicyParams{
				Name:        routeName,
				Namespace:   agent.Namespace,
				PodSelector: map[string]string{"app": "agent", "agent": agent.Name},
				Labels:      map[string]string{"app": "agent", "agent": agent.Name},
			}, secCfg, log); err != nil {
				log.Error(err, "failed to reconcile NetworkPolicy")
			}
		}
	}

	// Update status
	agent.Status.LinkedResources = make(map[string]string)
	agent.Status.LinkedResources["modelapi"] = agent.Spec.ModelAPI
	if memoryStoreName != "" {
		agent.Status.LinkedResources["memorystore"] = memoryStoreName
	}

	// Surface memory health as a condition without affecting agent readiness: a
	// degraded store leaves the agent serving short-term-only memory. Reconcile
	// the condition whenever a memory block is configured so a recovering store
	// or a remote->local move clears a stale MemoryDegraded=True.
	if agent.Spec.Config != nil && agent.Spec.Config.Memory != nil {
		if memoryDegraded {
			meta.SetStatusCondition(&agent.Status.Conditions, metav1.Condition{
				Type:    "MemoryDegraded",
				Status:  metav1.ConditionTrue,
				Reason:  "MemoryStoreNotReady",
				Message: memoryDegradedMsg,
			})
		} else {
			msg := "Memory is healthy"
			if memoryStoreName != "" {
				msg = fmt.Sprintf("MemoryStore %s is ready", memoryStoreName)
			}
			meta.SetStatusCondition(&agent.Status.Conditions, metav1.Condition{
				Type:    "MemoryDegraded",
				Status:  metav1.ConditionFalse,
				Reason:  "MemoryHealthy",
				Message: msg,
			})
		}
	}

	// Copy deployment status for rolling update visibility
	agent.Status.Deployment = util.CopyDeploymentStatus(deployment)

	// Check deployment readiness
	if deployment.Status.ReadyReplicas > 0 {
		agent.Status.Ready = true
		agent.Status.Phase = "Ready"
	} else {
		agent.Status.Phase = "Pending"
		agent.Status.Ready = false
	}

	agent.Status.Message = fmt.Sprintf("Deployment ready replicas: %d/%d", deployment.Status.ReadyReplicas, *deployment.Spec.Replicas)

	if err := r.Status().Update(ctx, agent); err != nil {
		if apierrors.IsConflict(err) {
			log.Info("conflict updating status, will retry on next reconcile")
			return ctrl.Result{}, nil
		}
		log.Error(err, "failed to update status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// applyGatewayRouting rewrites the resolved ModelAPI, MCP, peer, and memory
// endpoints to gateway-routed URLs when gateway routing is enabled. All
// referenced resources live in the agent's namespace, so each URL becomes
// http://<gatewayHost>/<namespace>/<type>/<name>, which the per-resource
// HTTPRoute matches and rewrites back to the workload. The gateway host is taken
// from explicit config or, failing that, the Gateway resource's status address;
// when neither is available the direct Service URLs are left untouched so
// connectivity is never silently broken.
func (r *AgentReconciler) applyGatewayRouting(
	ctx context.Context,
	agent *kaosv1alpha1.Agent,
	modelapi *kaosv1alpha1.ModelAPI,
	mcpServers map[string]string,
	peerAgents map[string]string,
	memoryStoreName string,
	memoryEndpoint *string,
	log logr.Logger,
) {
	secCfg := security.GetConfig()
	if !secCfg.GatewayRoutingEnabled() {
		return
	}

	host := strings.TrimSpace(secCfg.GatewayHost)
	if host == "" {
		resolved, err := gateway.StatusAddress(ctx, r.Client)
		if err != nil {
			log.Error(err, "failed to resolve gateway address for routing; using direct endpoints")
			return
		}
		host = resolved
	}
	if host == "" {
		log.Info("gateway routing enabled but no gateway host resolved; using direct endpoints")
		return
	}

	modelapi.Status.Endpoint = gateway.GatewayEndpoint(host, agent.Namespace, gateway.ResourceTypeModelAPI, modelapi.Name)
	for name := range mcpServers {
		mcpServers[name] = gateway.GatewayEndpoint(host, agent.Namespace, gateway.ResourceTypeMCP, name)
	}
	for name := range peerAgents {
		peerAgents[name] = gateway.GatewayEndpoint(host, agent.Namespace, gateway.ResourceTypeAgent, name)
	}
	// Only a resolved (Ready) memory endpoint is rewritten; an empty endpoint
	// means the store is absent or not ready and memory stays short-term only.
	if memoryEndpoint != nil && *memoryEndpoint != "" && memoryStoreName != "" {
		*memoryEndpoint = gateway.GatewayEndpoint(host, agent.Namespace, gateway.ResourceTypeMemoryStore, memoryStoreName)
	}
}

func resolveMemoryScope(mem *kaosv1alpha1.MemoryConfig, store *kaosv1alpha1.MemoryStore) string {
	if mem != nil && mem.Scope != "" {
		return mem.Scope
	}
	if store != nil && store.Spec.DefaultScope != "" {
		return store.Spec.DefaultScope
	}
	return "agent"
}

// agentDeploymentExists reports whether the agent's Deployment already exists.
// It is used to gate only the agent's initial creation on memory availability:
// a missing Deployment means "first creation" (gate when memory is unavailable),
// while an existing one means the agent is already running and must degrade
// rather than be gated.
func (r *AgentReconciler) agentDeploymentExists(ctx context.Context, agent *kaosv1alpha1.Agent) (bool, error) {
	deployment := &appsv1.Deployment{}
	name := fmt.Sprintf("agent-%s", agent.Name)
	err := r.Get(ctx, types.NamespacedName{Name: name, Namespace: agent.Namespace}, deployment)
	if err != nil {
		if apierrors.IsNotFound(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// constructDeployment creates a Deployment for the Agent
func (r *AgentReconciler) constructDeployment(agent *kaosv1alpha1.Agent, modelapi *kaosv1alpha1.ModelAPI, mcpServers map[string]string, peerAgents map[string]string, memoryEndpoint, memoryScope, tokenExchangeConfig string) (*appsv1.Deployment, error) {
	labels := map[string]string{
		"app":   "agent",
		"agent": agent.Name,
	}

	replicas := int32(1)

	// Build environment variables
	env := r.constructEnvVars(agent, modelapi, mcpServers, peerAgents, memoryEndpoint, memoryScope, tokenExchangeConfig)

	// Get agent image from environment (required - set via ConfigMap)
	agentImage := os.Getenv("DEFAULT_AGENT_IMAGE")
	if agentImage == "" {
		return nil, fmt.Errorf("DEFAULT_AGENT_IMAGE environment variable is required but not set")
	}

	container := corev1.Container{
		Name:            "agent",
		Image:           agentImage,
		ImagePullPolicy: corev1.PullIfNotPresent,
		Ports: []corev1.ContainerPort{
			{
				Name:          "http",
				ContainerPort: 8000,
				Protocol:      corev1.ProtocolTCP,
			},
		},
		Env: env,
		LivenessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path:   "/health",
					Port:   intstr.FromInt(8000),
					Scheme: corev1.URISchemeHTTP,
				},
			},
			InitialDelaySeconds: 5,
			PeriodSeconds:       10,
			TimeoutSeconds:      3,
			FailureThreshold:    3,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path:   "/ready",
					Port:   intstr.FromInt(8000),
					Scheme: corev1.URISchemeHTTP,
				},
			},
			InitialDelaySeconds: 3,
			PeriodSeconds:       5,
			TimeoutSeconds:      3,
			FailureThreshold:    2,
		},
	}

	basePodSpec := corev1.PodSpec{
		Containers: []corev1.Container{container},
	}
	if cfg := security.GetConfig(); cfg.ServiceAccountIdentityEnabled() {
		basePodSpec.ServiceAccountName = security.AgentServiceAccountName(agent.Name)
		basePodSpec.AutomountServiceAccountToken = ptr.To(false)
	}

	// Mount the per-agent credential Secret as a file so the runtime can re-read the
	// client_secret on rotation (when credential mounting is enabled).
	if volume, mount := buildAgentAuthVolume(agent); volume != nil {
		basePodSpec.Volumes = append(basePodSpec.Volumes, *volume)
		basePodSpec.Containers[0].VolumeMounts = append(basePodSpec.Containers[0].VolumeMounts, *mount)
	}

	// Apply spec.container override using strategic merge patch
	if agent.Spec.Container != nil {
		containerPatch := containerOverrideToPodSpecPatch(*agent.Spec.Container)
		if merged, err := util.MergePodSpec(basePodSpec, containerPatch); err == nil {
			basePodSpec = merged
		}
	}

	// Apply spec.podSpec override using strategic merge patch
	finalPodSpec := basePodSpec
	if agent.Spec.PodSpec != nil {
		if merged, err := util.MergePodSpec(basePodSpec, *agent.Spec.PodSpec); err == nil {
			finalPodSpec = merged
		}
	}

	// Compute hash of the pod spec for change detection
	podSpecHash := util.ComputePodSpecHash(finalPodSpec)

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("agent-%s", agent.Name),
			Namespace: agent.Namespace,
			Labels:    labels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
					Annotations: map[string]string{
						util.PodSpecHashAnnotation: podSpecHash,
					},
				},
				Spec: finalPodSpec,
			},
		},
	}

	return deployment, nil
}

// constructEnvVars builds environment variables for the agent
func (r *AgentReconciler) constructEnvVars(agent *kaosv1alpha1.Agent, modelapi *kaosv1alpha1.ModelAPI, mcpServers map[string]string, peerAgents map[string]string, memoryEndpoint, memoryScope, tokenExchangeConfig string) []corev1.EnvVar {
	var env []corev1.EnvVar

	// Agent identity and configuration
	env = append(env, corev1.EnvVar{
		Name:  "AGENT_NAME",
		Value: agent.Name,
	})

	if agent.Spec.Config != nil {
		if agent.Spec.Config.Description != "" {
			env = append(env, corev1.EnvVar{
				Name:  "AGENT_DESCRIPTION",
				Value: agent.Spec.Config.Description,
			})
		}

		if agent.Spec.Config.Instructions != "" {
			env = append(env, corev1.EnvVar{
				Name:  "AGENT_INSTRUCTIONS",
				Value: agent.Spec.Config.Instructions,
			})
		}

		if agent.Spec.Config.SystemPrompt != "" {
			env = append(env, corev1.EnvVar{
				Name:  "AGENT_SYSTEM_PROMPT",
				Value: agent.Spec.Config.SystemPrompt,
			})
		}
	}

	// ModelAPI configuration
	env = append(env, corev1.EnvVar{
		Name:  "MODEL_API_URL",
		Value: modelapi.Status.Endpoint,
	})

	// MODEL_NAME from required spec.model field
	env = append(env, corev1.EnvVar{
		Name:  "MODEL_NAME",
		Value: agent.Spec.Model,
	})

	// Reasoning loop configuration
	if agent.Spec.Config != nil && agent.Spec.Config.ReasoningLoopMaxSteps != nil {
		env = append(env, corev1.EnvVar{
			Name:  "AGENTIC_LOOP_MAX_STEPS",
			Value: fmt.Sprintf("%d", *agent.Spec.Config.ReasoningLoopMaxSteps),
		})
	}

	// Tool call mode configuration
	if agent.Spec.Config != nil && agent.Spec.Config.ToolCallMode != "" {
		env = append(env, corev1.EnvVar{
			Name:  "TOOL_CALL_MODE",
			Value: agent.Spec.Config.ToolCallMode,
		})
	}

	// Memory configuration
	if agent.Spec.Config != nil && agent.Spec.Config.Memory != nil {
		mem := agent.Spec.Config.Memory

		enabled := true
		if mem.Enabled != nil {
			enabled = *mem.Enabled
		}
		env = append(env, corev1.EnvVar{
			Name:  "MEMORY_ENABLED",
			Value: fmt.Sprintf("%t", enabled),
		})

		// Effective backend: explicit type when set, else derived from memoryStore
		// presence (remote when bound, local otherwise).
		effectiveType := mem.Type
		if effectiveType == "" {
			if mem.MemoryStore != "" {
				effectiveType = "remote"
			} else {
				effectiveType = "local"
			}
		}
		env = append(env, corev1.EnvVar{
			Name:  "MEMORY_TYPE",
			Value: effectiveType,
		})

		// The store endpoint is injected only for the remote backend; a local agent
		// runs the pod-local short-term fallback with no long-term tier.
		if effectiveType == "remote" && memoryEndpoint != "" {
			env = append(env, corev1.EnvVar{
				Name:  "MEMORY_STORE_ENDPOINT",
				Value: memoryEndpoint,
			})
		}

		if memoryScope != "" {
			env = append(env, corev1.EnvVar{
				Name:  "MEMORY_SCOPE",
				Value: memoryScope,
			})
		}
		defaultReadScope := mem.DefaultReadScope
		if defaultReadScope == "" {
			defaultReadScope = memoryScope
		}
		readScopes := mem.ReadScopes
		if len(readScopes) == 0 {
			readScopes = []string{defaultReadScope}
		}
		env = append(env,
			corev1.EnvVar{Name: "MEMORY_DEFAULT_READ_SCOPE", Value: defaultReadScope},
			corev1.EnvVar{Name: "MEMORY_READ_SCOPES", Value: strings.Join(readScopes, ",")},
		)
		if mem.Tools != "" {
			env = append(env, corev1.EnvVar{
				Name:  "MEMORY_TOOLS",
				Value: mem.Tools,
			})
		}
		if mem.FailureMode != "" {
			env = append(env, corev1.EnvVar{
				Name:  "MEMORY_FAILURE_MODE",
				Value: mem.FailureMode,
			})
		}
		if mem.ClientParams != nil {
			if mem.ClientParams.TokenBudget != nil {
				env = append(env, corev1.EnvVar{
					Name:  "MEMORY_SHORT_TERM_TOKEN_BUDGET",
					Value: fmt.Sprintf("%d", *mem.ClientParams.TokenBudget),
				})
			}
			if mem.ClientParams.RollingSummary != nil {
				env = append(env, corev1.EnvVar{
					Name:  "MEMORY_ROLLING_SUMMARY",
					Value: fmt.Sprintf("%t", *mem.ClientParams.RollingSummary),
				})
			}
		}

		// Always inject the fully-qualified agent identity so agent-scoped memory
		// is owned by a verifiable, unique principal rather than collapsing onto a
		// group partition when identity is absent.
		env = append(env, corev1.EnvVar{
			Name:  "AGENT_IDENTITY",
			Value: fmt.Sprintf("kaos://agent/%s/%s", agent.Namespace, agent.Name),
		})
	}

	// Autonomous configuration — goal presence activates autonomous mode
	if agent.Spec.Config != nil && agent.Spec.Config.Autonomous != nil {
		auto := agent.Spec.Config.Autonomous
		if auto.Goal != "" {
			env = append(env, corev1.EnvVar{
				Name:  "AUTONOMOUS_GOAL",
				Value: auto.Goal,
			})
		}
		if auto.IntervalSeconds != nil {
			env = append(env, corev1.EnvVar{
				Name:  "AUTONOMOUS_INTERVAL_SECONDS",
				Value: fmt.Sprintf("%d", *auto.IntervalSeconds),
			})
		}
		if auto.MaxIterRuntimeSeconds != nil {
			env = append(env, corev1.EnvVar{
				Name:  "AUTONOMOUS_MAX_ITER_RUNTIME_SECONDS",
				Value: fmt.Sprintf("%d", *auto.MaxIterRuntimeSeconds),
			})
		}
	}

	// Task budget configuration (A2A async task defaults)
	if agent.Spec.Config != nil && agent.Spec.Config.TaskConfig != nil {
		tc := agent.Spec.Config.TaskConfig
		if tc.MaxIterations != nil {
			env = append(env, corev1.EnvVar{
				Name:  "TASK_MAX_ITERATIONS",
				Value: fmt.Sprintf("%d", *tc.MaxIterations),
			})
		}
		if tc.MaxRuntimeSeconds != nil {
			env = append(env, corev1.EnvVar{
				Name:  "TASK_MAX_RUNTIME_SECONDS",
				Value: fmt.Sprintf("%d", *tc.MaxRuntimeSeconds),
			})
		}
		if tc.MaxToolCalls != nil {
			env = append(env, corev1.EnvVar{
				Name:  "TASK_MAX_TOOL_CALLS",
				Value: fmt.Sprintf("%d", *tc.MaxToolCalls),
			})
		}
	}

	// MCP Servers configuration
	if len(mcpServers) > 0 {
		mcpNames := make([]string, 0, len(mcpServers))
		for name := range mcpServers {
			mcpNames = append(mcpNames, name)
		}
		// Sort for deterministic order (prevents hash oscillation)
		sort.Strings(mcpNames)

		env = append(env, corev1.EnvVar{
			Name:  "MCP_SERVERS",
			Value: strings.Join(mcpNames, ","), // Comma-separated list
		})

		// Add individual MCP server URLs (in sorted order)
		for _, name := range mcpNames {
			endpoint := mcpServers[name]
			env = append(env, corev1.EnvVar{
				Name:  fmt.Sprintf("MCP_SERVER_%s_URL", name),
				Value: endpoint,
			})
		}
	}

	// Peer Agents configuration
	if len(peerAgents) > 0 {
		peerNames := make([]string, 0, len(peerAgents))
		for name := range peerAgents {
			peerNames = append(peerNames, name)
		}
		// Sort for deterministic order (prevents hash oscillation)
		sort.Strings(peerNames)

		env = append(env, corev1.EnvVar{
			Name:  "PEER_AGENTS",
			Value: strings.Join(peerNames, ","),
		})

		// Add individual peer agent card URLs (in sorted order)
		for _, name := range peerNames {
			endpoint := peerAgents[name]
			// Convert name to valid env var format (uppercase, replace hyphens with underscores)
			envName := strings.ToUpper(strings.ReplaceAll(name, "-", "_"))
			env = append(env, corev1.EnvVar{
				Name:  fmt.Sprintf("PEER_AGENT_%s_CARD_URL", envName),
				Value: endpoint,
			})
		}
	}

	// OpenTelemetry configuration - merge with global defaults
	var componentTelemetry *kaosv1alpha1.TelemetryConfig
	if agent.Spec.Config != nil {
		componentTelemetry = agent.Spec.Config.Telemetry
	}
	telemetryConfig := util.MergeTelemetryConfig(componentTelemetry)
	if telemetryConfig != nil {
		otelEnv := util.BuildTelemetryEnvVars(
			telemetryConfig,
			agent.Name,
			agent.Namespace,
		)
		env = append(env, otelEnv...)
	}

	// Add LOG_LEVEL env var (if not already set by user in spec.config.env)
	if logLevelEnv := util.BuildLogLevelEnvVar(env); logLevelEnv != nil {
		env = append(env, logLevelEnv...)
	}

	// Agent identity and credentials (when security credential mounting is enabled)
	env = append(env, buildAgentAuthEnvVars(agent)...)
	if tokenExchangeConfig != "" {
		env = append(env, corev1.EnvVar{Name: "KAOS_TOKEN_EXCHANGE_CONFIG", Value: tokenExchangeConfig})
	}

	return env
}

type agentTokenExchangeConfig struct {
	Issuer        string   `json:"issuer"`
	TokenEndpoint string   `json:"token_endpoint"`
	Audience      string   `json:"audience"`
	Targets       []string `json:"targets"`
}

func (r *AgentReconciler) tokenExchangeConfig(ctx context.Context, agent *kaosv1alpha1.Agent) (string, error) {
	if !strings.EqualFold(os.Getenv("TOKEN_EXCHANGE_ENABLED"), "true") {
		return "", nil
	}
	reflection := &corev1.ConfigMap{}
	if err := r.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: exchangeReflectionName}, reflection); err != nil {
		if apierrors.IsNotFound(err) {
			return "", nil
		}
		return "", fmt.Errorf("reading AIB exchange reflection: %w", err)
	}
	var targets []string
	rawTargets := reflection.Data[agent.Name]
	if rawTargets == "" {
		return "", nil
	}
	if err := json.Unmarshal([]byte(rawTargets), &targets); err != nil {
		return "", fmt.Errorf("reading reflected targets for Agent %s/%s: %w", agent.Namespace, agent.Name, err)
	}
	if len(targets) == 0 {
		return "", nil
	}
	sort.Strings(targets)
	cfg := security.GetConfig()
	data, err := json.Marshal(agentTokenExchangeConfig{
		Issuer: cfg.AgentIssuer(), TokenEndpoint: cfg.TokenEndpoint(),
		Audience: "token-exchange-broker", Targets: targets,
	})
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// buildAgentAuthEnvVars returns the agent-auth environment variables that give the
// agent its actor identity and, when provisioned, the credentials it uses to mint
// an actor token, under the provider-agnostic AGENT_AUTH_ prefix. The client_id/client_secret
// are sourced from the per-agent credential Secret as optional references, so the pod can
// start before the identity projection controller has written the Secret; the values appear once it exists.
// Returns nil when credential mounting is not enabled, leaving existing pods unchanged.
func buildAgentAuthEnvVars(agent *kaosv1alpha1.Agent) []corev1.EnvVar {
	cfg := security.GetConfig()
	if cfg.ServiceAccountIdentityEnabled() {
		return []corev1.EnvVar{
			{Name: "AGENT_AUTH_IDENTITY", Value: fmt.Sprintf("kaos://agent/%s/%s", agent.Namespace, agent.Name)},
			{Name: "AGENT_AUTH_TOKEN_FILE", Value: cfg.ServiceAccountTokenPath},
		}
	}
	if !cfg.CredentialMountingEnabled() {
		return nil
	}

	secretName := cfg.CredentialSecretName(agent.Name)
	optional := true
	env := []corev1.EnvVar{
		{
			Name:  "AGENT_AUTH_IDENTITY",
			Value: fmt.Sprintf("kaos://agent/%s/%s", agent.Namespace, agent.Name),
		},
		{
			Name: "AGENT_AUTH_CLIENT_ID",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: secretName},
					Key:                  "client_id",
					Optional:             &optional,
				},
			},
		},
		{
			Name: "AGENT_AUTH_CLIENT_SECRET",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: secretName},
					Key:                  "client_secret",
					Optional:             &optional,
				},
			},
		},
	}
	if endpoint := cfg.TokenEndpoint(); endpoint != "" {
		env = append(env, corev1.EnvVar{Name: "AGENT_AUTH_TOKEN_ENDPOINT", Value: endpoint})
	}
	// Point the runtime at the mounted client_secret file so it can re-read the
	// credential on rotation. The SecretKeyRef env above stays as a startup fallback.
	env = append(env, corev1.EnvVar{
		Name:  "AGENT_AUTH_CLIENT_SECRET_FILE",
		Value: cfg.CredentialSecretFilePath(),
	})
	return env
}

// buildAgentAuthVolume returns the active issuer's credential or projected-token
// volume and read-only mount.
func buildAgentAuthVolume(agent *kaosv1alpha1.Agent) (*corev1.Volume, *corev1.VolumeMount) {
	cfg := security.GetConfig()
	if cfg.ServiceAccountIdentityEnabled() {
		expiration := cfg.ServiceAccountTokenExpirationSeconds
		volume := &corev1.Volume{
			Name: "agent-auth-token",
			VolumeSource: corev1.VolumeSource{Projected: &corev1.ProjectedVolumeSource{
				Sources: []corev1.VolumeProjection{{ServiceAccountToken: &corev1.ServiceAccountTokenProjection{
					Audience:          cfg.ServiceAccountAudience,
					ExpirationSeconds: &expiration,
					Path:              cfg.ServiceAccountTokenFilename(),
				}}},
			}},
		}
		return volume, &corev1.VolumeMount{Name: volume.Name, MountPath: cfg.ServiceAccountTokenMountDir(), ReadOnly: true}
	}
	if !cfg.CredentialMountingEnabled() {
		return nil, nil
	}
	optional := true
	volume := &corev1.Volume{
		Name: "agent-auth-credentials",
		VolumeSource: corev1.VolumeSource{
			Secret: &corev1.SecretVolumeSource{
				SecretName: cfg.CredentialSecretName(agent.Name),
				Optional:   &optional,
			},
		},
	}
	mount := &corev1.VolumeMount{
		Name:      "agent-auth-credentials",
		MountPath: cfg.CredentialMountDir(),
		ReadOnly:  true,
	}
	return volume, mount
}

func (r *AgentReconciler) reconcileAgentServiceAccount(ctx context.Context, agent *kaosv1alpha1.Agent) error {
	name := security.AgentServiceAccountName(agent.Name)
	cfg := security.GetConfig()
	if !cfg.ServiceAccountIdentityEnabled() {
		existing := &corev1.ServiceAccount{}
		if err := r.Get(ctx, types.NamespacedName{Namespace: agent.Namespace, Name: name}, existing); err == nil {
			if existing.Labels["app.kubernetes.io/managed-by"] == "kaos-operator" {
				return r.Delete(ctx, existing)
			}
			return nil
		} else if !apierrors.IsNotFound(err) {
			return err
		}
		return nil
	}

	serviceAccount := &corev1.ServiceAccount{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: agent.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, serviceAccount, func() error {
		serviceAccount.Labels = map[string]string{
			"app.kubernetes.io/managed-by": "kaos-operator",
			"kaos.tools/agent":             agent.Name,
		}
		serviceAccount.AutomountServiceAccountToken = ptr.To(false)
		return controllerutil.SetControllerReference(agent, serviceAccount, r.Scheme)
	})
	return err
}

// constructService creates a Service for A2A communication
func (r *AgentReconciler) constructService(agent *kaosv1alpha1.Agent) *corev1.Service {
	labels := map[string]string{
		"app":   "agent",
		"agent": agent.Name,
	}

	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("agent-%s", agent.Name),
			Namespace: agent.Namespace,
			Labels:    labels,
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       8000,
					TargetPort: intstr.FromInt(8000),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Selector: labels,
		},
	}

	return service
}

// containerOverrideToPodSpecPatch converts a ContainerOverride to a PodSpec patch
// for strategic merge with the base container named "agent".
func containerOverrideToPodSpecPatch(override kaosv1alpha1.ContainerOverride) corev1.PodSpec {
	c := corev1.Container{Name: "agent"}
	if override.Image != "" {
		c.Image = override.Image
	}
	if len(override.Command) > 0 {
		c.Command = override.Command
	}
	if len(override.Args) > 0 {
		c.Args = override.Args
	}
	if override.Resources != nil {
		c.Resources = *override.Resources
	}
	if len(override.Env) > 0 {
		c.Env = override.Env
	}
	return corev1.PodSpec{
		Containers: []corev1.Container{c},
	}
}

// SetupWithManager sets up the controller with the Manager.
func (r *AgentReconciler) SetupWithManager(mgr ctrl.Manager) error {
	// Map ModelAPI changes to related Agents
	mapModelAPIToAgents := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []ctrl.Request {
		modelapi := obj.(*kaosv1alpha1.ModelAPI)
		// Find all Agents in the same namespace
		agentList := &kaosv1alpha1.AgentList{}
		if err := r.List(ctx, agentList, client.InNamespace(modelapi.Namespace)); err != nil {
			return []ctrl.Request{}
		}

		requests := []ctrl.Request{}
		for _, agent := range agentList.Items {
			if agent.Spec.ModelAPI == modelapi.Name {
				requests = append(requests, ctrl.Request{
					NamespacedName: types.NamespacedName{Name: agent.Name, Namespace: agent.Namespace},
				})
			}
		}
		return requests
	})

	// Map MCPServer changes to related Agents
	mapMCPServerToAgents := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []ctrl.Request {
		mcpserver := obj.(*kaosv1alpha1.MCPServer)
		// Find all Agents in the same namespace
		agentList := &kaosv1alpha1.AgentList{}
		if err := r.List(ctx, agentList, client.InNamespace(mcpserver.Namespace)); err != nil {
			return []ctrl.Request{}
		}

		requests := []ctrl.Request{}
		for _, agent := range agentList.Items {
			for _, mcpName := range agent.Spec.MCPServers {
				if mcpName == mcpserver.Name {
					requests = append(requests, ctrl.Request{
						NamespacedName: types.NamespacedName{Name: agent.Name, Namespace: agent.Namespace},
					})
				}
			}
		}
		return requests
	})

	// Map MemoryStore changes to related Agents so a store appearing or becoming
	// Ready promptly requeues the agents bound to it (memory binding recovery).
	mapMemoryStoreToAgents := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []ctrl.Request {
		store := obj.(*kaosv1alpha1.MemoryStore)
		agentList := &kaosv1alpha1.AgentList{}
		if err := r.List(ctx, agentList, client.InNamespace(store.Namespace)); err != nil {
			return []ctrl.Request{}
		}

		requests := []ctrl.Request{}
		for _, agent := range agentList.Items {
			if agent.Spec.Config != nil && agent.Spec.Config.Memory != nil &&
				agent.Spec.Config.Memory.MemoryStore == store.Name {
				requests = append(requests, ctrl.Request{
					NamespacedName: types.NamespacedName{Name: agent.Name, Namespace: agent.Namespace},
				})
			}
		}
		return requests
	})

	mapExchangeReflectionToAgents := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []ctrl.Request {
		reflection := obj.(*corev1.ConfigMap)
		if reflection.Name != exchangeReflectionName {
			return nil
		}
		agents := &kaosv1alpha1.AgentList{}
		if err := r.List(ctx, agents, client.InNamespace(reflection.Namespace)); err != nil {
			return nil
		}
		requests := make([]ctrl.Request, 0, len(agents.Items))
		for _, agent := range agents.Items {
			requests = append(requests, ctrl.Request{NamespacedName: types.NamespacedName{Name: agent.Name, Namespace: agent.Namespace}})
		}
		return requests
	})

	builder := ctrl.NewControllerManagedBy(mgr).
		For(&kaosv1alpha1.Agent{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ServiceAccount{}).
		Watches(&kaosv1alpha1.ModelAPI{}, mapModelAPIToAgents).
		Watches(&kaosv1alpha1.MCPServer{}, mapMCPServerToAgents).
		Watches(&kaosv1alpha1.MemoryStore{}, mapMemoryStoreToAgents).
		Watches(&corev1.ConfigMap{}, mapExchangeReflectionToAgents)

	// Own HTTPRoutes if Gateway API is enabled
	if gateway.GetConfig().Enabled {
		builder = builder.Owns(&gatewayv1.HTTPRoute{})
	}

	return builder.Complete(r)
}

// validateAgentModel checks if the agent's model is supported by the ModelAPI
func (r *AgentReconciler) validateAgentModel(agent *kaosv1alpha1.Agent, modelapi *kaosv1alpha1.ModelAPI) error {
	agentModel := agent.Spec.Model

	// Get supported models from spec (models is required with MinItems=1)
	var supportedModels []string
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeProxy && modelapi.Spec.ProxyConfig != nil {
		supportedModels = modelapi.Spec.ProxyConfig.Models
	} else if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted && modelapi.Spec.HostedConfig != nil {
		supportedModels = []string{modelapi.Spec.HostedConfig.Model}
	}

	for _, pattern := range supportedModels {
		// Full wildcard matches everything
		if pattern == "*" {
			return nil
		}

		// Exact match
		if pattern == agentModel {
			return nil
		}

		// Provider wildcard: "openai/*" matches "openai/gpt-4"
		if strings.HasSuffix(pattern, "/*") {
			prefix := strings.TrimSuffix(pattern, "*")
			if strings.HasPrefix(agentModel, prefix) {
				return nil
			}
		}
	}

	return fmt.Errorf("model %q not supported by ModelAPI %q (supported: %v)", agentModel, modelapi.Name, supportedModels)
}
