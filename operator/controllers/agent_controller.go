package controllers

import (
	"context"
	"fmt"

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
	"sigs.k8s.io/controller-runtime/pkg/log"

	agenticv1alpha1 "agentic.example.com/agentic-operator/api/v1alpha1"
)

const agentFinalizerName = "agentic.example.com/agent-finalizer"

// AgentReconciler reconciles an Agent object
type AgentReconciler struct {
	client.Client
	Log    ctrl.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=agentic.example.com,resources=agents,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=agentic.example.com,resources=agents/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=agentic.example.com,resources=agents/finalizers,verbs=update
//+kubebuilder:rbac:groups=agentic.example.com,resources=modelapis,verbs=get;list;watch
//+kubebuilder:rbac:groups=agentic.example.com,resources=mcpservers,verbs=get;list;watch
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *AgentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	agent := &agenticv1alpha1.Agent{}
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
	modelapi := &agenticv1alpha1.ModelAPI{}
	err := r.Get(ctx, types.NamespacedName{Name: agent.Spec.ModelAPI, Namespace: agent.Namespace}, modelapi)
	if err != nil {
		log.Error(err, "unable to fetch ModelAPI", "modelAPI", agent.Spec.ModelAPI)
		agent.Status.Phase = "Failed"
		agent.Status.Message = fmt.Sprintf("Failed to resolve ModelAPI: %v", err)
		r.Status().Update(ctx, agent)
		return ctrl.Result{}, err
	}

	if !modelapi.Status.Ready {
		log.Info("ModelAPI not ready, waiting", "modelAPI", agent.Spec.ModelAPI)
		agent.Status.Phase = "Waiting"
		agent.Status.Message = "ModelAPI is not ready"
		r.Status().Update(ctx, agent)
		return ctrl.Result{}, nil
	}

	// Resolve MCPServer references
	mcpServers := make(map[string]string)
	for _, mcpName := range agent.Spec.MCPServers {
		mcp := &agenticv1alpha1.MCPServer{}
		err := r.Get(ctx, types.NamespacedName{Name: mcpName, Namespace: agent.Namespace}, mcp)
		if err != nil {
			log.Error(err, "unable to fetch MCPServer", "mcpserver", mcpName)
			agent.Status.Phase = "Failed"
			agent.Status.Message = fmt.Sprintf("Failed to resolve MCPServer %s: %v", mcpName, err)
			r.Status().Update(ctx, agent)
			return ctrl.Result{}, err
		}

		if !mcp.Status.Ready {
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
			peerAgent := &agenticv1alpha1.Agent{}
			err := r.Get(ctx, types.NamespacedName{Name: peerName, Namespace: agent.Namespace}, peerAgent)
			if err != nil {
				log.Error(err, "unable to fetch peer Agent", "agent", peerName)
				// Peer agents are not critical, just log
				continue
			}

			if peerAgent.Status.Endpoint != "" {
				peerAgents[peerName] = peerAgent.Status.Endpoint
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
	}

	// Create or update A2A Service (if expose is enabled)
	if agent.Spec.AgentNetwork != nil && agent.Spec.AgentNetwork.Expose {
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

		// Set endpoint for A2A
		agent.Status.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local:8000/agent/card", serviceName, agent.Namespace)
	}

	// Update status
	agent.Status.LinkedResources = make(map[string]string)
	agent.Status.LinkedResources["modelapi"] = agent.Spec.ModelAPI

	// Check deployment readiness
	if deployment.Status.ReadyReplicas > 0 {
		agent.Status.Ready = true
		agent.Status.Phase = "Ready"
		agent.Status.ObservedReplicas = deployment.Status.ReadyReplicas
	} else {
		agent.Status.Phase = "Pending"
		agent.Status.Ready = false
		agent.Status.ObservedReplicas = deployment.Status.AvailableReplicas
	}

	agent.Status.Message = fmt.Sprintf("Deployment ready replicas: %d/%d", deployment.Status.ReadyReplicas, *deployment.Spec.Replicas)

	if err := r.Status().Update(ctx, agent); err != nil {
		log.Error(err, "failed to update status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// constructDeployment creates a Deployment for the Agent
func (r *AgentReconciler) constructDeployment(agent *agenticv1alpha1.Agent, modelapi *agenticv1alpha1.ModelAPI, mcpServers map[string]string, peerAgents map[string]string) *appsv1.Deployment {
	labels := map[string]string{
		"app":   "agent",
		"agent": agent.Name,
	}

	replicas := int32(1)
	if agent.Spec.Replicas != nil {
		replicas = *agent.Spec.Replicas
	}

	// Build environment variables
	env := r.constructEnvVars(agent, modelapi, mcpServers, peerAgents)

	container := corev1.Container{
		Name:  "agent",
		Image: "agentic-runtime:latest", // Should be available from docker build
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

	// Add resource requests if specified
	if agent.Spec.Resources != nil {
		container.Resources = *agent.Spec.Resources
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
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{container},
				},
			},
		},
	}

	return deployment
}

// constructEnvVars builds environment variables for the agent
func (r *AgentReconciler) constructEnvVars(agent *agenticv1alpha1.Agent, modelapi *agenticv1alpha1.ModelAPI, mcpServers map[string]string, peerAgents map[string]string) []corev1.EnvVar {
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
			Value: fmt.Sprintf("%v", peerNames),
		})

		// Add individual peer agent card URLs
		for name, endpoint := range peerAgents {
			env = append(env, corev1.EnvVar{
				Name:  fmt.Sprintf("PEER_AGENT_%s_CARD_URL", name),
				Value: endpoint,
			})
		}
	}

	return env
}

// constructService creates a Service for A2A communication
func (r *AgentReconciler) constructService(agent *agenticv1alpha1.Agent) *corev1.Service {
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
	return ctrl.NewControllerManagedBy(mgr).
		For(&agenticv1alpha1.Agent{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Complete(r)
}
