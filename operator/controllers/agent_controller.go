package controllers

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/go-logr/logr"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
	"github.com/axsaucedo/kaos/operator/pkg/util"
)

const agentFinalizerName = "kaos.tools/agent-finalizer"

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
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *AgentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	agent := &kaosv1alpha1.Agent{}
	if err := r.Get(ctx, req.NamespacedName, agent); err != nil {
		log.Error(err, "unable to fetch Agent")
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
	}

	// Resolve ModelAPI reference
	modelapi := &kaosv1alpha1.ModelAPI{}
	err := r.Get(ctx, types.NamespacedName{Name: agent.Spec.ModelAPI, Namespace: agent.Namespace}, modelapi)
	if err != nil {
		log.Error(err, "unable to fetch ModelAPI", "modelAPI", agent.Spec.ModelAPI)
		agent.Status.Phase = "Failed"
		agent.Status.Message = fmt.Sprintf("Failed to resolve ModelAPI: %v", err)
		r.Status().Update(ctx, agent)
		return ctrl.Result{}, err
	}

	// Check if we should wait for dependencies (default true)
	waitForDeps := agent.Spec.WaitForDependencies == nil || *agent.Spec.WaitForDependencies

	if !modelapi.Status.Ready && waitForDeps {
		log.Info("ModelAPI not ready, waiting", "modelAPI", agent.Spec.ModelAPI)
		agent.Status.Phase = "Waiting"
		agent.Status.Message = "ModelAPI is not ready"
		r.Status().Update(ctx, agent)
		return ctrl.Result{}, nil
	}

	// Resolve MCPServer references
	mcpServers := make(map[string]string)
	for _, mcpName := range agent.Spec.MCPServers {
		mcp := &kaosv1alpha1.MCPServer{}
		err := r.Get(ctx, types.NamespacedName{Name: mcpName, Namespace: agent.Namespace}, mcp)
		if err != nil {
			log.Error(err, "unable to fetch MCPServer", "mcpserver", mcpName)
			agent.Status.Phase = "Failed"
			agent.Status.Message = fmt.Sprintf("Failed to resolve MCPServer %s: %v", mcpName, err)
			r.Status().Update(ctx, agent)
			return ctrl.Result{}, err
		}

		if !mcp.Status.Ready && waitForDeps {
			log.Info("MCPServer not ready, waiting", "mcpserver", mcpName)
			agent.Status.Phase = "Waiting"
			agent.Status.Message = fmt.Sprintf("MCPServer %s is not ready", mcpName)
			r.Status().Update(ctx, agent)
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

	// Create or update Deployment
	deployment := &appsv1.Deployment{}
	deploymentName := fmt.Sprintf("agent-%s", agent.Name)
	err = r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: agent.Namespace}, deployment)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Deployment
		deployment = r.constructDeployment(agent, modelapi, mcpServers, peerAgents)
		if err := controllerutil.SetControllerReference(agent, deployment, r.Scheme); err != nil {
			log.Error(err, "failed to set controller reference")
			return ctrl.Result{}, err
		}

		log.Info("Creating Deployment", "name", deployment.Name)
		if err := r.Create(ctx, deployment); err != nil {
			log.Error(err, "failed to create Deployment")
			agent.Status.Phase = "Failed"
			agent.Status.Message = fmt.Sprintf("Failed to create Deployment: %v", err)
			r.Status().Update(ctx, agent)
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "failed to get Deployment")
		return ctrl.Result{}, err
	} else {
		// Deployment exists - check if env vars need updating (e.g., peer agents discovered)
		desiredDeployment := r.constructDeployment(agent, modelapi, mcpServers, peerAgents)
		if !r.envVarsEqual(deployment.Spec.Template.Spec.Containers[0].Env, desiredDeployment.Spec.Template.Spec.Containers[0].Env) {
			log.Info("Updating Deployment with new environment", "name", deployment.Name)
			deployment.Spec.Template.Spec.Containers[0].Env = desiredDeployment.Spec.Template.Spec.Containers[0].Env
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
				r.Status().Update(ctx, agent)
				return ctrl.Result{}, err
			}
		} else if err != nil {
			log.Error(err, "failed to get Service")
			return ctrl.Result{}, err
		}

		// Set endpoint for A2A (base URL only - clients append paths like /.well-known/agent)
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
	}

	// Update status
	agent.Status.LinkedResources = make(map[string]string)
	agent.Status.LinkedResources["modelapi"] = agent.Spec.ModelAPI

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
		log.Error(err, "failed to update status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// constructDeployment creates a Deployment for the Agent
func (r *AgentReconciler) constructDeployment(agent *kaosv1alpha1.Agent, modelapi *kaosv1alpha1.ModelAPI, mcpServers map[string]string, peerAgents map[string]string) *appsv1.Deployment {
	labels := map[string]string{
		"app":   "agent",
		"agent": agent.Name,
	}

	replicas := int32(1)

	// Build environment variables
	env := r.constructEnvVars(agent, modelapi, mcpServers, peerAgents)

	// Get agent image from environment or use default
	agentImage := os.Getenv("DEFAULT_AGENT_IMAGE")
	if agentImage == "" {
		agentImage = "kaos-agent:latest"
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
			InitialDelaySeconds: 30,
			PeriodSeconds:       10,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path:   "/ready",
					Port:   intstr.FromInt(8000),
					Scheme: corev1.URISchemeHTTP,
				},
			},
			InitialDelaySeconds: 10,
			PeriodSeconds:       5,
		},
	}

	basePodSpec := corev1.PodSpec{
		Containers: []corev1.Container{container},
	}

	// Apply podSpec override using strategic merge patch if provided
	finalPodSpec := basePodSpec
	if agent.Spec.PodSpec != nil {
		merged, err := util.MergePodSpec(basePodSpec, *agent.Spec.PodSpec)
		if err == nil {
			finalPodSpec = merged
		}
	}

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
				},
				Spec: finalPodSpec,
			},
		},
	}

	return deployment
}

// constructEnvVars builds environment variables for the agent
func (r *AgentReconciler) constructEnvVars(agent *kaosv1alpha1.Agent, modelapi *kaosv1alpha1.ModelAPI, mcpServers map[string]string, peerAgents map[string]string) []corev1.EnvVar {
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

		// Add user-provided config env vars
		env = append(env, agent.Spec.Config.Env...)
	}

	// ModelAPI configuration
	env = append(env, corev1.EnvVar{
		Name:  "MODEL_API_URL",
		Value: modelapi.Status.Endpoint,
	})

	// Default MODEL_NAME if not provided in user env vars
	// Users can override via config.env
	hasModelName := false
	if agent.Spec.Config != nil {
		for _, e := range agent.Spec.Config.Env {
			if e.Name == "MODEL_NAME" {
				hasModelName = true
				break
			}
		}
	}
	if !hasModelName {
		env = append(env, corev1.EnvVar{
			Name:  "MODEL_NAME",
			Value: "smollm2:135m", // Default model
		})
	}

	// Enable debug memory endpoints for testing (can be disabled via AGENT_DEBUG_MEMORY_ENDPOINTS=false)
	hasDebugMemory := false
	if agent.Spec.Config != nil {
		for _, e := range agent.Spec.Config.Env {
			if e.Name == "AGENT_DEBUG_MEMORY_ENDPOINTS" {
				hasDebugMemory = true
				break
			}
		}
	}
	if !hasDebugMemory {
		env = append(env, corev1.EnvVar{
			Name:  "AGENT_DEBUG_MEMORY_ENDPOINTS",
			Value: "true", // Enable by default for testing
		})
	}

	// Reasoning loop configuration
	if agent.Spec.Config != nil && agent.Spec.Config.ReasoningLoopMaxSteps != nil {
		env = append(env, corev1.EnvVar{
			Name:  "AGENTIC_LOOP_MAX_STEPS",
			Value: fmt.Sprintf("%d", *agent.Spec.Config.ReasoningLoopMaxSteps),
		})
	}

	// MCP Servers configuration
	if len(mcpServers) > 0 {
		mcpNames := make([]string, 0, len(mcpServers))
		for name := range mcpServers {
			mcpNames = append(mcpNames, name)
		}

		env = append(env, corev1.EnvVar{
			Name:  "MCP_SERVERS",
			Value: fmt.Sprintf("%v", mcpNames), // Will be comma-separated in JSON
		})

		// Add individual MCP server URLs
		for name, endpoint := range mcpServers {
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

		env = append(env, corev1.EnvVar{
			Name:  "PEER_AGENTS",
			Value: strings.Join(peerNames, ","),
		})

		// Add individual peer agent card URLs
		for name, endpoint := range peerAgents {
			// Convert name to valid env var format (uppercase, replace hyphens with underscores)
			envName := strings.ToUpper(strings.ReplaceAll(name, "-", "_"))
			env = append(env, corev1.EnvVar{
				Name:  fmt.Sprintf("PEER_AGENT_%s_CARD_URL", envName),
				Value: endpoint,
			})
		}
	}

	return env
}

// envVarsEqual compares two env var lists for equality
func (r *AgentReconciler) envVarsEqual(a, b []corev1.EnvVar) bool {
	if len(a) != len(b) {
		return false
	}
	aMap := make(map[string]string)
	for _, e := range a {
		aMap[e.Name] = e.Value
	}
	for _, e := range b {
		if val, ok := aMap[e.Name]; !ok || val != e.Value {
			return false
		}
	}
	return true
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

	builder := ctrl.NewControllerManagedBy(mgr).
		For(&kaosv1alpha1.Agent{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Watches(&kaosv1alpha1.ModelAPI{}, mapModelAPIToAgents).
		Watches(&kaosv1alpha1.MCPServer{}, mapMCPServerToAgents)

	// Own HTTPRoutes if Gateway API is enabled
	if gateway.GetConfig().Enabled {
		builder = builder.Owns(&gatewayv1.HTTPRoute{})
	}

	return builder.Complete(r)
}
