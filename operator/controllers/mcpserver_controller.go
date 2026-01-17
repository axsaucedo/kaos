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
	"sigs.k8s.io/controller-runtime/pkg/log"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
	"github.com/axsaucedo/kaos/operator/pkg/util"
)

const mcpServerFinalizerName = "kaos.tools/mcpserver-finalizer"

// MCPServerReconciler reconciles a MCPServer object
type MCPServerReconciler struct {
	client.Client
	Log    logr.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=kaos.tools,resources=mcpservers,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=kaos.tools,resources=mcpservers/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=kaos.tools,resources=mcpservers/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *MCPServerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	mcpserver := &kaosv1alpha1.MCPServer{}
	if err := r.Get(ctx, req.NamespacedName, mcpserver); err != nil {
		// Ignore not-found errors (resource was deleted)
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
	deploymentName := fmt.Sprintf("mcpserver-%s", mcpserver.Name)
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
	} else {
		// Deployment exists - check if spec has changed using hash annotation
		desiredDeployment := r.constructDeployment(mcpserver)
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

	// Create or update Service
	service := &corev1.Service{}
	serviceName := fmt.Sprintf("mcpserver-%s", mcpserver.Name)
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

	// Create HTTPRoute if Gateway API is enabled
	timeout := ""
	if mcpserver.Spec.GatewayRoute != nil && mcpserver.Spec.GatewayRoute.Timeout != "" {
		timeout = mcpserver.Spec.GatewayRoute.Timeout
	}
	if err := gateway.ReconcileHTTPRoute(ctx, r.Client, r.Scheme, mcpserver, gateway.HTTPRouteParams{
		ResourceType: gateway.ResourceTypeMCP,
		ResourceName: mcpserver.Name,
		Namespace:    mcpserver.Namespace,
		ServiceName:  serviceName,
		ServicePort:  8000,
		Labels:       map[string]string{"app": "mcpserver", "mcpserver": mcpserver.Name},
		Timeout:      timeout,
	}, log); err != nil {
		log.Error(err, "failed to reconcile HTTPRoute")
	}

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
func (r *MCPServerReconciler) constructDeployment(mcpserver *kaosv1alpha1.MCPServer) *appsv1.Deployment {
	labels := map[string]string{
		"app":       "mcpserver",
		"mcpserver": mcpserver.Name,
	}

	replicas := int32(1)

	// Construct container based on server type
	var container corev1.Container
	if mcpserver.Spec.Type == kaosv1alpha1.MCPServerTypePython {
		container = r.constructPythonContainer(mcpserver)
	} else {
		// Default to Python if type is unknown
		container = r.constructPythonContainer(mcpserver)
	}

	basePodSpec := corev1.PodSpec{
		Containers: []corev1.Container{container},
	}

	// Apply podSpec override using strategic merge patch if provided
	finalPodSpec := basePodSpec
	if mcpserver.Spec.PodSpec != nil {
		merged, err := util.MergePodSpec(basePodSpec, *mcpserver.Spec.PodSpec)
		if err == nil {
			finalPodSpec = merged
		}
	}

	// Compute hash of the pod spec for change detection
	podSpecHash := util.ComputePodSpecHash(finalPodSpec)

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcpserver-%s", mcpserver.Name),
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
					Annotations: map[string]string{
						util.PodSpecHashAnnotation: podSpecHash,
					},
				},
				Spec: finalPodSpec,
			},
		},
	}

	return deployment
}

// constructPythonContainer creates a container that runs MCP server
func (r *MCPServerReconciler) constructPythonContainer(mcpserver *kaosv1alpha1.MCPServer) corev1.Container {
	env := append([]corev1.EnvVar{}, mcpserver.Spec.Config.Env...)

	var image string
	var command []string

	// Get default MCP server image from environment
	defaultMcpImage := os.Getenv("DEFAULT_MCP_SERVER_IMAGE")
	if defaultMcpImage == "" {
		defaultMcpImage = "axsauze/kaos-agent:latest"
	}

	// Check if using tools config
	if mcpserver.Spec.Config.Tools != nil {
		if mcpserver.Spec.Config.Tools.FromString != "" {
			// Use the kaos-agent image with MCP_TOOLS_STRING
			image = defaultMcpImage
			command = []string{"python", "-m", "mcptools.server"}
			env = append(env, corev1.EnvVar{
				Name:  "MCP_TOOLS_STRING",
				Value: mcpserver.Spec.Config.Tools.FromString,
			})
		} else if mcpserver.Spec.Config.Tools.FromSecretKeyRef != nil {
			// Use the kaos-agent image with MCP_TOOLS_STRING from secret
			image = defaultMcpImage
			command = []string{"python", "-m", "mcptools.server"}
			env = append(env, corev1.EnvVar{
				Name: "MCP_TOOLS_STRING",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: mcpserver.Spec.Config.Tools.FromSecretKeyRef,
				},
			})
		} else if mcpserver.Spec.Config.Tools.FromPackage != "" {
			// Use uvx with the package name
			packageName := mcpserver.Spec.Config.Tools.FromPackage
			moduleName := strings.ReplaceAll(packageName, "-", "_")
			image = "python:3.12-slim"
			command = []string{
				"sh",
				"-c",
				fmt.Sprintf("pip install %s && ( %s || python -m %s )", packageName, packageName, moduleName),
			}
		}
	}

	container := corev1.Container{
		Name:            "mcp-server",
		Image:           image,
		ImagePullPolicy: corev1.PullIfNotPresent,
		Command:         command,
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
				TCPSocket: &corev1.TCPSocketAction{
					Port: intstr.FromInt(8000),
				},
			},
			InitialDelaySeconds: 20,
			PeriodSeconds:       10,
			TimeoutSeconds:      3,
			FailureThreshold:    3,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				TCPSocket: &corev1.TCPSocketAction{
					Port: intstr.FromInt(8000),
				},
			},
			InitialDelaySeconds: 15,
			PeriodSeconds:       5,
			TimeoutSeconds:      3,
			FailureThreshold:    2,
		},
	}

	return container
}

// constructService creates a Service for the MCPServer
func (r *MCPServerReconciler) constructService(mcpserver *kaosv1alpha1.MCPServer) *corev1.Service {
	labels := map[string]string{
		"app":       "mcpserver",
		"mcpserver": mcpserver.Name,
	}

	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcpserver-%s", mcpserver.Name),
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
	builder := ctrl.NewControllerManagedBy(mgr).
		For(&kaosv1alpha1.MCPServer{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{})

	if gateway.GetConfig().Enabled {
		builder = builder.Owns(&gatewayv1.HTTPRoute{})
	}

	return builder.Complete(r)
}
