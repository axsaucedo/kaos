package controllers

import (
	"context"
	"fmt"
	"os"

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

	agenticv1alpha1 "agentic.example.com/agentic-operator/api/v1alpha1"
	"agentic.example.com/agentic-operator/pkg/gateway"
	"agentic.example.com/agentic-operator/pkg/util"
)

const modelAPIFinalizerName = "ethical.institute/modelapi-finalizer"

// ModelAPIReconciler reconciles a ModelAPI object
type ModelAPIReconciler struct {
	client.Client
	Log    logr.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=ethical.institute,resources=modelapis,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=ethical.institute,resources=modelapis/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=ethical.institute,resources=modelapis/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *ModelAPIReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	modelapi := &agenticv1alpha1.ModelAPI{}
	if err := r.Get(ctx, req.NamespacedName, modelapi); err != nil {
		log.Error(err, "unable to fetch ModelAPI")
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Handle deletion with finalizer
	if modelapi.ObjectMeta.DeletionTimestamp != nil {
		if controllerutil.ContainsFinalizer(modelapi, modelAPIFinalizerName) {
			// Perform cleanup
			log.Info("Deleting ModelAPI", "name", modelapi.Name)
			controllerutil.RemoveFinalizer(modelapi, modelAPIFinalizerName)
			if err := r.Update(ctx, modelapi); err != nil {
				log.Error(err, "failed to remove finalizer")
				return ctrl.Result{}, err
			}
		}
		return ctrl.Result{}, nil
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(modelapi, modelAPIFinalizerName) {
		controllerutil.AddFinalizer(modelapi, modelAPIFinalizerName)
		if err := r.Update(ctx, modelapi); err != nil {
			log.Error(err, "failed to add finalizer")
			return ctrl.Result{}, err
		}
	}

	// Set initial status
	if modelapi.Status.Phase == "" {
		modelapi.Status.Phase = "Pending"
		modelapi.Status.Ready = false
		if err := r.Status().Update(ctx, modelapi); err != nil {
			log.Error(err, "failed to update status")
			return ctrl.Result{}, err
		}
	}

	// Create ConfigMap for Proxy mode - always needed since we use config file mode
	needsConfigMap := modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy &&
		modelapi.Spec.ProxyConfig != nil

	if needsConfigMap {
		configmap := &corev1.ConfigMap{}
		configmapName := fmt.Sprintf("litellm-config-%s", modelapi.Name)
		err := r.Get(ctx, types.NamespacedName{Name: configmapName, Namespace: modelapi.Namespace}, configmap)

		if err != nil && apierrors.IsNotFound(err) {
			// Create new ConfigMap with user-provided config or auto-generated wildcard
			configmap = r.constructConfigMap(modelapi)
			if err := controllerutil.SetControllerReference(modelapi, configmap, r.Scheme); err != nil {
				log.Error(err, "failed to set controller reference for ConfigMap")
				return ctrl.Result{}, err
			}

			log.Info("Creating ConfigMap", "name", configmap.Name)
			if err := r.Create(ctx, configmap); err != nil {
				log.Error(err, "failed to create ConfigMap")
				modelapi.Status.Phase = "Failed"
				modelapi.Status.Message = fmt.Sprintf("Failed to create ConfigMap: %v", err)
				r.Status().Update(ctx, modelapi)
				return ctrl.Result{}, err
			}
		} else if err != nil {
			log.Error(err, "failed to get ConfigMap")
			modelapi.Status.Phase = "Failed"
			modelapi.Status.Message = fmt.Sprintf("Failed to get ConfigMap: %v", err)
			r.Status().Update(ctx, modelapi)
			return ctrl.Result{}, err
		}
	}

	// Create or update Deployment
	deployment := &appsv1.Deployment{}
	deploymentName := fmt.Sprintf("modelapi-%s", modelapi.Name)
	err := r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: modelapi.Namespace}, deployment)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Deployment
		deployment = r.constructDeployment(modelapi)
		if err := controllerutil.SetControllerReference(modelapi, deployment, r.Scheme); err != nil {
			log.Error(err, "failed to set controller reference")
			return ctrl.Result{}, err
		}

		log.Info("Creating Deployment", "name", deployment.Name)
		if err := r.Create(ctx, deployment); err != nil {
			log.Error(err, "failed to create Deployment")
			modelapi.Status.Phase = "Failed"
			modelapi.Status.Message = fmt.Sprintf("Failed to create Deployment: %v", err)
			r.Status().Update(ctx, modelapi)
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "failed to get Deployment")
		return ctrl.Result{}, err
	}

	// Create or update Service
	service := &corev1.Service{}
	serviceName := fmt.Sprintf("modelapi-%s", modelapi.Name)
	err = r.Get(ctx, types.NamespacedName{Name: serviceName, Namespace: modelapi.Namespace}, service)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Service
		service = r.constructService(modelapi)
		if err := controllerutil.SetControllerReference(modelapi, service, r.Scheme); err != nil {
			log.Error(err, "failed to set controller reference")
			return ctrl.Result{}, err
		}

		log.Info("Creating Service", "name", service.Name)
		if err := r.Create(ctx, service); err != nil {
			log.Error(err, "failed to create Service")
			modelapi.Status.Phase = "Failed"
			modelapi.Status.Message = fmt.Sprintf("Failed to create Service: %v", err)
			r.Status().Update(ctx, modelapi)
			return ctrl.Result{}, err
		}
	} else if err != nil {
		log.Error(err, "failed to get Service")
		return ctrl.Result{}, err
	}

	// Update status - use correct port based on mode
	port := 8000
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeHosted {
		port = 11434
	}
	modelapi.Status.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local:%d", serviceName, modelapi.Namespace, port)

	// Create HTTPRoute if Gateway API is enabled
	timeout := ""
	if modelapi.Spec.GatewayRoute != nil && modelapi.Spec.GatewayRoute.Timeout != "" {
		timeout = modelapi.Spec.GatewayRoute.Timeout
	}
	if err := gateway.ReconcileHTTPRoute(ctx, r.Client, r.Scheme, modelapi, gateway.HTTPRouteParams{
		ResourceType: gateway.ResourceTypeModelAPI,
		ResourceName: modelapi.Name,
		Namespace:    modelapi.Namespace,
		ServiceName:  serviceName,
		ServicePort:  int32(port),
		Labels:       map[string]string{"app": "modelapi", "modelapi": modelapi.Name},
		Timeout:      timeout,
	}, log); err != nil {
		log.Error(err, "failed to reconcile HTTPRoute")
	}

	// Check deployment readiness
	if deployment.Status.ReadyReplicas > 0 {
		modelapi.Status.Ready = true
		modelapi.Status.Phase = "Ready"
	} else {
		modelapi.Status.Phase = "Pending"
		modelapi.Status.Ready = false
	}

	modelapi.Status.Message = fmt.Sprintf("Deployment ready replicas: %d/%d", deployment.Status.ReadyReplicas, *deployment.Spec.Replicas)

	if err := r.Status().Update(ctx, modelapi); err != nil {
		log.Error(err, "failed to update status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// constructDeployment creates a Deployment for the ModelAPI
func (r *ModelAPIReconciler) constructDeployment(modelapi *agenticv1alpha1.ModelAPI) *appsv1.Deployment {
	labels := map[string]string{
		"app":      "modelapi",
		"modelapi": modelapi.Name,
	}

	replicas := int32(1)

	// Build volumes list - add litellm-config for Proxy mode (always uses config file)
	volumes := []corev1.Volume{}
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy && modelapi.Spec.ProxyConfig != nil {
		volumes = append(volumes, corev1.Volume{
			Name: "litellm-config",
			VolumeSource: corev1.VolumeSource{
				ConfigMap: &corev1.ConfigMapVolumeSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: fmt.Sprintf("litellm-config-%s", modelapi.Name),
					},
				},
			},
		})
	}

	// Build init containers for Hosted mode (pull the model)
	initContainers := []corev1.Container{}
	ollamaImage := os.Getenv("DEFAULT_OLLAMA_IMAGE")
	if ollamaImage == "" {
		ollamaImage = "alpine/ollama:latest"
	}
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeHosted && modelapi.Spec.HostedConfig != nil && modelapi.Spec.HostedConfig.Model != "" {
		// Init container starts Ollama server, pulls model, then exits
		// The model is stored in the emptyDir volume shared with main container
		volumes = append(volumes, corev1.Volume{
			Name: "ollama-data",
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		})
		initContainers = append(initContainers, corev1.Container{
			Name:            "pull-model",
			Image:           ollamaImage,
			ImagePullPolicy: corev1.PullIfNotPresent,
			Command:         []string{"/bin/sh", "-c"},
			Args: []string{
				fmt.Sprintf("ollama serve & OLLAMA_PID=$! && sleep 5 && ollama pull %s && kill $OLLAMA_PID", modelapi.Spec.HostedConfig.Model),
			},
			VolumeMounts: []corev1.VolumeMount{
				{Name: "ollama-data", MountPath: "/root/.ollama"},
			},
		})
	}

	basePodSpec := corev1.PodSpec{
		InitContainers: initContainers,
		Containers: []corev1.Container{
			r.constructContainer(modelapi),
		},
		Volumes: volumes,
	}

	// Apply podSpec override using strategic merge patch if provided
	finalPodSpec := basePodSpec
	if modelapi.Spec.PodSpec != nil {
		merged, err := util.MergePodSpec(basePodSpec, *modelapi.Spec.PodSpec)
		if err == nil {
			finalPodSpec = merged
		}
	}

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("modelapi-%s", modelapi.Name),
			Namespace: modelapi.Namespace,
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

// constructContainer creates the container spec based on ModelAPI mode
func (r *ModelAPIReconciler) constructContainer(modelapi *agenticv1alpha1.ModelAPI) corev1.Container {
	var image string
	var args []string
	var env []corev1.EnvVar
	var port int32 = 8000
	var healthPath string = "/health"

	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy {
		// LiteLLM Proxy mode - always uses config file
		image = os.Getenv("DEFAULT_LITELLM_IMAGE")
		if image == "" {
			image = "ghcr.io/berriai/litellm:main-latest"
		}
		port = 8000
		// Use /health/liveliness for faster probe responses
		// /health does a full backend check which can timeout
		healthPath = "/health/liveliness"

		// Always use config file mode for consistency:
		// - User provides configYaml → use their config directly
		// - User provides apiBase → generate wildcard config to forward all requests
		args = []string{"--config", "/etc/litellm/config.yaml", "--port", "8000"}

		// Add user-provided env vars for proxy
		if modelapi.Spec.ProxyConfig != nil {
			env = append(env, modelapi.Spec.ProxyConfig.Env...)
		}

		// Add default proxy env vars only if not already set by user
		hasLiteLLMLog := false
		for _, e := range env {
			if e.Name == "LITELLM_LOG" {
				hasLiteLLMLog = true
				break
			}
		}
		if !hasLiteLLMLog {
			env = append(env, corev1.EnvVar{
				Name:  "LITELLM_LOG",
				Value: "INFO",
			})
		}

	} else {
		// Ollama Hosted mode
		image = os.Getenv("DEFAULT_OLLAMA_IMAGE")
		if image == "" {
			image = "alpine/ollama:latest"
		}
		args = []string{}
		port = 11434
		healthPath = "/"

		// Add user-provided env vars for hosted
		if modelapi.Spec.HostedConfig != nil {
			env = append(env, modelapi.Spec.HostedConfig.Env...)
		}
	}

	// Build volume mounts - add litellm-config for Proxy mode (always uses config file)
	volumeMounts := []corev1.VolumeMount{}
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy && modelapi.Spec.ProxyConfig != nil {
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "litellm-config",
			MountPath: "/etc/litellm",
		})
	}
	// Add ollama-data volume mount for Hosted mode
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeHosted && modelapi.Spec.HostedConfig != nil && modelapi.Spec.HostedConfig.Model != "" {
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "ollama-data",
			MountPath: "/root/.ollama",
		})
	}

	container := corev1.Container{
		Name:            "model-api",
		Image:           image,
		ImagePullPolicy: corev1.PullIfNotPresent,
		Args:            args,
		Ports: []corev1.ContainerPort{
			{
				Name:          "http",
				ContainerPort: port,
				Protocol:      corev1.ProtocolTCP,
			},
		},
		Env:           env,
		VolumeMounts:  volumeMounts,
		LivenessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path:   healthPath,
					Port:   intstr.FromInt(int(port)),
					Scheme: corev1.URISchemeHTTP,
				},
			},
			InitialDelaySeconds: 30,
			PeriodSeconds:       10,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path:   healthPath,
					Port:   intstr.FromInt(int(port)),
					Scheme: corev1.URISchemeHTTP,
				},
			},
			InitialDelaySeconds: 15,
			PeriodSeconds:       5,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		},
	}

	return container
}

// constructService creates a Service for the ModelAPI
func (r *ModelAPIReconciler) constructService(modelapi *agenticv1alpha1.ModelAPI) *corev1.Service {
	labels := map[string]string{
		"app":      "modelapi",
		"modelapi": modelapi.Name,
	}

	// Use different ports based on mode
	var port int32 = 8000
	var targetPort int32 = 8000
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeHosted {
		port = 11434
		targetPort = 11434
	}

	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("modelapi-%s", modelapi.Name),
			Namespace: modelapi.Namespace,
			Labels:    labels,
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       port,
					TargetPort: intstr.FromInt(int(targetPort)),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Selector: labels,
		},
	}

	return service
}

// constructConfigMap creates a ConfigMap with LiteLLM configuration
// If user provides configYaml, use it directly
// Otherwise, generate a wildcard config to forward all requests to apiBase
func (r *ModelAPIReconciler) constructConfigMap(modelapi *agenticv1alpha1.ModelAPI) *corev1.ConfigMap {
	configYaml := ""

	if modelapi.Spec.ProxyConfig != nil {
		if modelapi.Spec.ProxyConfig.ConfigYaml != nil && modelapi.Spec.ProxyConfig.ConfigYaml.FromString != "" {
			// Use user-provided configYaml directly
			configYaml = modelapi.Spec.ProxyConfig.ConfigYaml.FromString
		} else if modelapi.Spec.ProxyConfig.APIBase != "" {
			// Generate wildcard config for proxying any model to the apiBase
			// This allows requests like "ollama/smollm2:135m" to be forwarded to the backend
			configYaml = fmt.Sprintf(`# Auto-generated wildcard config - forwards any model to backend
model_list:
  - model_name: "*"
    litellm_params:
      model: "*"
      api_base: "%s"

litellm_settings:
  drop_params: true
`, modelapi.Spec.ProxyConfig.APIBase)
		} else if modelapi.Spec.ProxyConfig.Model != "" {
			// Model specified without apiBase - generate minimal config for mock testing
			// This allows mock_response to work without a real backend
			configYaml = fmt.Sprintf(`# Auto-generated config for mock/test mode
model_list:
  - model_name: "%s"
    litellm_params:
      model: "%s"

litellm_settings:
  drop_params: true
`, modelapi.Spec.ProxyConfig.Model, modelapi.Spec.ProxyConfig.Model)
		}
	}

	configmap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("litellm-config-%s", modelapi.Name),
			Namespace: modelapi.Namespace,
			Labels: map[string]string{
				"app":      "modelapi",
				"modelapi": modelapi.Name,
			},
		},
		Data: map[string]string{
			"config.yaml": configYaml,
		},
	}

	return configmap
}

// SetupWithManager sets up the controller with the Manager.
func (r *ModelAPIReconciler) SetupWithManager(mgr ctrl.Manager) error {
	builder := ctrl.NewControllerManagedBy(mgr).
		For(&agenticv1alpha1.ModelAPI{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ConfigMap{})

	if gateway.GetConfig().Enabled {
		builder = builder.Owns(&gatewayv1.HTTPRoute{})
	}

	return builder.Complete(r)
}
