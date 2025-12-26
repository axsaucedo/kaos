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

const mcpServerFinalizerName = "agentic.example.com/mcpserver-finalizer"

// MCPServerReconciler reconciles a MCPServer object
type MCPServerReconciler struct {
	client.Client
	Log    ctrl.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=agentic.example.com,resources=mcpservers,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=agentic.example.com,resources=mcpservers/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=agentic.example.com,resources=mcpservers/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *MCPServerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	mcpserver := &agenticv1alpha1.MCPServer{}
	if err := r.Get(ctx, req.NamespacedName, mcpserver); err != nil {
		log.Error(err, "unable to fetch MCPServer")
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Handle deletion with finalizer
	if mcpserver.ObjectMeta.DeletionTimestamp != nil {
		if controllerutil.ContainsFinalizer(mcpserver, mcpServerFinalizerName) {
			log.Info("Deleting MCPServer", "name", mcpserver.Name)
			controllerutil.RemoveFinalizer(mcpserver, mcpServerFinalizerName)
			if err := r.Update(ctx, mcpserver); err != nil {
				log.Error(err, "failed to remove finalizer")
				return ctrl.Result{}, err
			}
		}
		return ctrl.Result{}, nil
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(mcpserver, mcpServerFinalizerName) {
		controllerutil.AddFinalizer(mcpserver, mcpServerFinalizerName)
		if err := r.Update(ctx, mcpserver); err != nil {
			log.Error(err, "failed to add finalizer")
			return ctrl.Result{}, err
		}
	}

	// Set initial status
	if mcpserver.Status.Phase == "" {
		mcpserver.Status.Phase = "Pending"
		mcpserver.Status.Ready = false
		if err := r.Status().Update(ctx, mcpserver); err != nil {
			log.Error(err, "failed to update status")
			return ctrl.Result{}, err
		}
	}

	// Create or update Deployment
	deployment := &appsv1.Deployment{}
	deploymentName := fmt.Sprintf("mcp-%s", mcpserver.Name)
	err := r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: mcpserver.Namespace}, deployment)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Deployment
		deployment = r.constructDeployment(mcpserver)
		if err := controllerutil.SetControllerReference(mcpserver, deployment, r.Scheme); err != nil {
			log.Error(err, "failed to set controller reference")
			return ctrl.Result{}, err
		}

		log.Info("Creating Deployment", "name", deployment.Name)
		if err := r.Create(ctx, deployment); err != nil {
			log.Error(err, "failed to create Deployment")
			mcpserver.Status.Phase = "Failed"
			mcpserver.Status.Message = fmt.Sprintf("Failed to create Deployment: %v", err)
			r.Status().Update(ctx, mcpserver)
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "failed to get Deployment")
		return ctrl.Result{}, err
	}

	// Create or update Service
	service := &corev1.Service{}
	serviceName := fmt.Sprintf("mcp-%s", mcpserver.Name)
	err = r.Get(ctx, types.NamespacedName{Name: serviceName, Namespace: mcpserver.Namespace}, service)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Service
		service = r.constructService(mcpserver)
		if err := controllerutil.SetControllerReference(mcpserver, service, r.Scheme); err != nil {
			log.Error(err, "failed to set controller reference")
			return ctrl.Result{}, err
		}

		log.Info("Creating Service", "name", service.Name)
		if err := r.Create(ctx, service); err != nil {
			log.Error(err, "failed to create Service")
			mcpserver.Status.Phase = "Failed"
			mcpserver.Status.Message = fmt.Sprintf("Failed to create Service: %v", err)
			r.Status().Update(ctx, mcpserver)
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "failed to get Service")
		return ctrl.Result{}, err
	}

	// Update status
	mcpserver.Status.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local:8000", serviceName, mcpserver.Namespace)

	// Check deployment readiness
	if deployment.Status.ReadyReplicas > 0 {
		mcpserver.Status.Ready = true
		mcpserver.Status.Phase = "Ready"
	} else {
		mcpserver.Status.Phase = "Pending"
		mcpserver.Status.Ready = false
	}

	mcpserver.Status.Message = fmt.Sprintf("Deployment ready replicas: %d/%d", deployment.Status.ReadyReplicas, *deployment.Spec.Replicas)

	if err := r.Status().Update(ctx, mcpserver); err != nil {
		log.Error(err, "failed to update status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// constructDeployment creates a Deployment for the MCPServer
func (r *MCPServerReconciler) constructDeployment(mcpserver *agenticv1alpha1.MCPServer) *appsv1.Deployment {
	labels := map[string]string{
		"app":       "mcpserver",
		"mcpserver": mcpserver.Name,
	}

	replicas := int32(1)

	// Construct container based on server type
	var container corev1.Container
	if mcpserver.Spec.Type == agenticv1alpha1.MCPServerTypePython {
		container = r.constructPythonContainer(mcpserver)
	} else {
		// Default to Python if type is unknown
		container = r.constructPythonContainer(mcpserver)
	}

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", mcpserver.Name),
			Namespace: mcpserver.Namespace,
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

// constructPythonContainer creates a container that runs MCP server via uvx
func (r *MCPServerReconciler) constructPythonContainer(mcpserver *agenticv1alpha1.MCPServer) corev1.Container {
	env := mcpserver.Spec.Config.Env

	container := corev1.Container{
		Name:  "mcp-server",
		Image: "python:3.11-slim",
		Command: []string{
			"sh",
			"-c",
			fmt.Sprintf("pip install uvx && uvx %s", mcpserver.Spec.Config.MCP),
		},
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
					Path:   "/health",
					Port:   intstr.FromInt(8000),
					Scheme: corev1.URISchemeHTTP,
				},
			},
			InitialDelaySeconds: 10,
			PeriodSeconds:       5,
		},
	}

	// Add resource requests if specified
	if mcpserver.Spec.Resources != nil {
		container.Resources = *mcpserver.Spec.Resources
	}

	return container
}

// constructService creates a Service for the MCPServer
func (r *MCPServerReconciler) constructService(mcpserver *agenticv1alpha1.MCPServer) *corev1.Service {
	labels := map[string]string{
		"app":       "mcpserver",
		"mcpserver": mcpserver.Name,
	}

	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", mcpserver.Name),
			Namespace: mcpserver.Namespace,
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
func (r *MCPServerReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&agenticv1alpha1.MCPServer{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Complete(r)
}
