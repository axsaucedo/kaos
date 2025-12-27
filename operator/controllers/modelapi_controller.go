package controllers

import (
	"context"
	"fmt"

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

	agenticv1alpha1 "agentic.example.com/agentic-operator/api/v1alpha1"
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

	// Create or update ConfigMap for LiteLLM config (only for Proxy mode)
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy {
		configmap := &corev1.ConfigMap{}
		configmapName := fmt.Sprintf("litellm-config")
		err := r.Get(ctx, types.NamespacedName{Name: configmapName, Namespace: modelapi.Namespace}, configmap)

		if err != nil && apierrors.IsNotFound(err) {
			// Create new ConfigMap
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

	// Update status
	modelapi.Status.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local:8000", serviceName, modelapi.Namespace)

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

	// Build volumes list - only add litellm-config for Proxy mode
	volumes := []corev1.Volume{}
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy {
		volumes = append(volumes, corev1.Volume{
			Name: "litellm-config",
			VolumeSource: corev1.VolumeSource{
				ConfigMap: &corev1.ConfigMapVolumeSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: "litellm-config",
					},
				},
			},
		})
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
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						r.constructContainer(modelapi),
					},
					Volumes: volumes,
				},
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
		// LiteLLM Proxy mode
		image = "litellm/litellm:latest"
		args = []string{"--config", "/etc/litellm/config.yaml", "--port", "8000"}
		port = 8000
		healthPath = "/health"

		// Add user-provided env vars for proxy
		if modelapi.Spec.ProxyConfig != nil {
			env = append(env, modelapi.Spec.ProxyConfig.Env...)
		}

		// Add default proxy env vars
		env = append(env, corev1.EnvVar{
			Name:  "LITELLM_LOG",
			Value: "INFO",
		})

	} else {
		// Ollama Hosted mode
		image = "ollama/ollama:latest"
		args = []string{}
		port = 11434
		healthPath = "/"

		// Add user-provided env vars for hosted
		if modelapi.Spec.ServerConfig != nil {
			env = append(env, modelapi.Spec.ServerConfig.Env...)
		}
	}

	// Build volume mounts - only add litellm-config for Proxy mode
	volumeMounts := []corev1.VolumeMount{}
	if modelapi.Spec.Mode == agenticv1alpha1.ModelAPIModeProxy {
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "litellm-config",
			MountPath: "/etc/litellm",
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

	// Add resource requests if specified
	if modelapi.Spec.ServerConfig != nil && modelapi.Spec.ServerConfig.Resources != nil {
		container.Resources = *modelapi.Spec.ServerConfig.Resources
	}

	return container
}

// constructService creates a Service for the ModelAPI
func (r *ModelAPIReconciler) constructService(modelapi *agenticv1alpha1.ModelAPI) *corev1.Service {
	labels := map[string]string{
		"app":      "modelapi",
		"modelapi": modelapi.Name,
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

// constructConfigMap creates a ConfigMap with LiteLLM configuration
func (r *ModelAPIReconciler) constructConfigMap(modelapi *agenticv1alpha1.ModelAPI) *corev1.ConfigMap {
	// Create a basic LiteLLM config that routes to Ollama
	litellmConfig := `model_list:
  - model_name: "smollm2:135m"
    litellm_params:
      model: "ollama/smollm2:135m"
      api_base: "http://host.docker.internal:11434"
      stream_timeout: 600

  - model_name: "llama2"
    litellm_params:
      model: "ollama/llama2"
      api_base: "http://host.docker.internal:11434"
      stream_timeout: 600

general_settings:
  completion_model: "smollm2:135m"
  function_calling: false
  drop_params: true
  enable_model_cost_map: false

router_settings:
  enable_cooldowns: true
  cooldown_time: 60
  request_timeout: 600
`

	configmap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "litellm-config",
			Namespace: modelapi.Namespace,
			Labels: map[string]string{
				"app":      "modelapi",
				"modelapi": modelapi.Name,
			},
		},
		Data: map[string]string{
			"config.yaml": litellmConfig,
		},
	}

	return configmap
}

// SetupWithManager sets up the controller with the Manager.
func (r *ModelAPIReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&agenticv1alpha1.ModelAPI{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}
