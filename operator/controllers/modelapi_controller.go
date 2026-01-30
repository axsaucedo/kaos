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
	"gopkg.in/yaml.v3"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
	"github.com/axsaucedo/kaos/operator/pkg/util"
)

const modelAPIFinalizerName = "kaos.tools/modelapi-finalizer"

// ModelAPIReconciler reconciles a ModelAPI object
type ModelAPIReconciler struct {
	client.Client
	Log    logr.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=kaos.tools,resources=modelapis,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=kaos.tools,resources=modelapis/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=kaos.tools,resources=modelapis/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *ModelAPIReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	modelapi := &kaosv1alpha1.ModelAPI{}
	if err := r.Get(ctx, req.NamespacedName, modelapi); err != nil {
		// Ignore not-found errors (resource was deleted)
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
	needsConfigMap := modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeProxy &&
		modelapi.Spec.ProxyConfig != nil

	// Validate telemetry config
	telemetry := util.MergeTelemetryConfig(modelapi.Spec.Telemetry)
	if !util.IsTelemetryConfigValid(telemetry) {
		log.Info("WARNING: telemetry.enabled=true but endpoint is empty; telemetry will not function", "modelapi", modelapi.Name)
	}

	// Warn if telemetry is enabled for Ollama (Hosted mode) - OTel not supported
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted {
		if telemetry != nil && telemetry.Enabled {
			log.Info("WARNING: OpenTelemetry telemetry is not supported for Ollama (Hosted mode). "+
				"Traces and metrics will not be collected.", "modelapi", modelapi.Name)
			// Update status message to warn user
			if modelapi.Status.Message == "" {
				modelapi.Status.Message = "Warning: Telemetry enabled but Ollama does not support OTel natively"
				r.Status().Update(ctx, modelapi)
			}
		}
	}

	// Validate configYaml against models list if both are provided
	if needsConfigMap && modelapi.Spec.ProxyConfig.ConfigYaml != nil &&
		modelapi.Spec.ProxyConfig.ConfigYaml.FromString != "" {
		if err := r.validateConfigYamlModels(modelapi.Spec.ProxyConfig); err != nil {
			log.Error(err, "configYaml validation failed")
			modelapi.Status.Phase = "Failed"
			modelapi.Status.Message = err.Error()
			r.Status().Update(ctx, modelapi)
			return ctrl.Result{}, nil
		}
	}

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
		} else {
			// ConfigMap exists - check if it needs updating
			desiredConfigMap := r.constructConfigMap(modelapi)
			if configmap.Data["config.yaml"] != desiredConfigMap.Data["config.yaml"] {
				log.Info("Updating ConfigMap", "name", configmap.Name)
				configmap.Data = desiredConfigMap.Data
				if err := r.Update(ctx, configmap); err != nil {
					log.Error(err, "failed to update ConfigMap")
					return ctrl.Result{}, err
				}
			}
		}
	}

	// Create or update Deployment
	deployment := &appsv1.Deployment{}
	deploymentName := fmt.Sprintf("modelapi-%s", modelapi.Name)
	err := r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: modelapi.Namespace}, deployment)

	if err != nil && apierrors.IsNotFound(err) {
		// Create new Deployment
		deployment, err = r.constructDeployment(modelapi)
		if err != nil {
			log.Error(err, "failed to construct Deployment")
			modelapi.Status.Phase = "Failed"
			modelapi.Status.Message = fmt.Sprintf("Failed to construct Deployment: %v", err)
			r.Status().Update(ctx, modelapi)
			return ctrl.Result{}, err
		}
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
	} else {
		// Deployment exists - check if spec has changed using hash annotation
		desiredDeployment, err := r.constructDeployment(modelapi)
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
	} else {
		// Service exists - check if port needs to be updated (mode changed)
		desiredService := r.constructService(modelapi)
		currentPort := service.Spec.Ports[0].Port
		desiredPort := desiredService.Spec.Ports[0].Port

		if currentPort != desiredPort {
			log.Info("Updating Service due to port change", "name", service.Name,
				"currentPort", currentPort, "desiredPort", desiredPort)
			service.Spec.Ports = desiredService.Spec.Ports
			if err := r.Update(ctx, service); err != nil {
				log.Error(err, "failed to update Service")
				return ctrl.Result{}, err
			}
		}
	}

	// Update status - use correct port based on mode
	port := 8000
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted {
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

	// Copy deployment status for rolling update visibility
	modelapi.Status.Deployment = util.CopyDeploymentStatus(deployment)

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
func (r *ModelAPIReconciler) constructDeployment(modelapi *kaosv1alpha1.ModelAPI) (*appsv1.Deployment, error) {
	labels := map[string]string{
		"app":      "modelapi",
		"modelapi": modelapi.Name,
	}

	replicas := int32(1)

	// Build volumes list - add litellm-config for Proxy mode (always uses config file)
	volumes := []corev1.Volume{}
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeProxy && modelapi.Spec.ProxyConfig != nil {
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
	if ollamaImage == "" && modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted {
		return nil, fmt.Errorf("DEFAULT_OLLAMA_IMAGE environment variable is required but not set")
	}
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted && modelapi.Spec.HostedConfig != nil && modelapi.Spec.HostedConfig.Model != "" {
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

	container, err := r.constructContainer(modelapi)
	if err != nil {
		return nil, err
	}

	basePodSpec := corev1.PodSpec{
		InitContainers: initContainers,
		Containers: []corev1.Container{
			container,
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

	// Compute hash of the pod spec for change detection
	podSpecHash := util.ComputePodSpecHash(finalPodSpec)

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

// constructContainer creates the container spec based on ModelAPI mode
func (r *ModelAPIReconciler) constructContainer(modelapi *kaosv1alpha1.ModelAPI) (corev1.Container, error) {
	var image string
	var args []string
	var env []corev1.EnvVar
	var port int32 = 8000
	var healthPath string = "/health"

	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeProxy {
		// LiteLLM Proxy mode - always uses config file
		image = os.Getenv("DEFAULT_LITELLM_IMAGE")
		if image == "" {
			return corev1.Container{}, fmt.Errorf("DEFAULT_LITELLM_IMAGE environment variable is required but not set")
		}
		port = 8000
		// Use /health/liveliness for faster probe responses
		// /health does a full backend check which can timeout
		healthPath = "/health/liveliness"

		// Always use config file mode for consistency:
		// - User provides configYaml → use their config directly
		// - User provides apiBase → generate wildcard config to forward all requests
		args = []string{"--config", "/etc/litellm/config.yaml", "--port", "8000"}

		// Add PROXY_API_BASE env var if apiBase is configured
		if modelapi.Spec.ProxyConfig != nil && modelapi.Spec.ProxyConfig.APIBase != "" {
			env = append(env, corev1.EnvVar{
				Name:  "PROXY_API_BASE",
				Value: modelapi.Spec.ProxyConfig.APIBase,
			})
		}

		// Add PROXY_API_KEY env var if apiKey is configured
		if modelapi.Spec.ProxyConfig != nil && modelapi.Spec.ProxyConfig.APIKey != nil {
			apiKey := modelapi.Spec.ProxyConfig.APIKey
			if apiKey.Value != "" {
				env = append(env, corev1.EnvVar{
					Name:  "PROXY_API_KEY",
					Value: apiKey.Value,
				})
			} else if apiKey.ValueFrom != nil {
				if apiKey.ValueFrom.SecretKeyRef != nil {
					env = append(env, corev1.EnvVar{
						Name: "PROXY_API_KEY",
						ValueFrom: &corev1.EnvVarSource{
							SecretKeyRef: apiKey.ValueFrom.SecretKeyRef,
						},
					})
				} else if apiKey.ValueFrom.ConfigMapKeyRef != nil {
					env = append(env, corev1.EnvVar{
						Name: "PROXY_API_KEY",
						ValueFrom: &corev1.EnvVarSource{
							ConfigMapKeyRef: apiKey.ValueFrom.ConfigMapKeyRef,
						},
					})
				}
			}
		}

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
			// Map LOG_LEVEL to LITELLM_LOG (LiteLLM supports DEBUG, INFO, WARNING, ERROR)
			litellmLogLevel := util.GetDefaultLogLevel()
			// TRACE -> DEBUG for LiteLLM (no TRACE level)
			if litellmLogLevel == "TRACE" {
				litellmLogLevel = "DEBUG"
			}
			env = append(env, corev1.EnvVar{
				Name:  "LITELLM_LOG",
				Value: litellmLogLevel,
			})
		}

		// Add OTel env vars for LiteLLM when telemetry is enabled
		telemetry := util.MergeTelemetryConfig(modelapi.Spec.Telemetry)
		if telemetry != nil && telemetry.Enabled {
			// LiteLLM uses OTEL_EXPORTER to select exporter type
			// Use "otlp_grpc" for gRPC collector (port 4317) or "otlp_http" for HTTP (port 4318)
			env = append(env, corev1.EnvVar{
				Name:  "OTEL_EXPORTER",
				Value: "otlp_grpc",
			})
			if telemetry.Endpoint != "" {
				// Use standard OTEL_EXPORTER_OTLP_ENDPOINT env var
				env = append(env, corev1.EnvVar{
					Name:  "OTEL_EXPORTER_OTLP_ENDPOINT",
					Value: telemetry.Endpoint,
				})
			}
			// Standard OTel service name
			env = append(env, corev1.EnvVar{
				Name:  "OTEL_SERVICE_NAME",
				Value: modelapi.Name,
			})
			// Exclude health check endpoints from OTEL traces (reduces noise from K8s probes)
			// Uses OTEL_PYTHON_EXCLUDED_URLS (generic) since LiteLLM may use various instrumentations
			// LiteLLM health endpoints: /health/liveliness, /health/liveness, /health/readiness
			env = append(env, corev1.EnvVar{
				Name:  "OTEL_PYTHON_EXCLUDED_URLS",
				Value: "/health",
			})
		}

	} else {
		// Ollama Hosted mode
		image = os.Getenv("DEFAULT_OLLAMA_IMAGE")
		if image == "" {
			return corev1.Container{}, fmt.Errorf("DEFAULT_OLLAMA_IMAGE environment variable is required but not set")
		}
		args = []string{}
		port = 11434
		healthPath = "/"

		// Add user-provided env vars for hosted
		if modelapi.Spec.HostedConfig != nil {
			env = append(env, modelapi.Spec.HostedConfig.Env...)
		}

		// Map LOG_LEVEL to OLLAMA_DEBUG (Ollama uses 0=INFO, 1=DEBUG, 2=TRACE)
		hasOllamaDebug := false
		for _, e := range env {
			if e.Name == "OLLAMA_DEBUG" {
				hasOllamaDebug = true
				break
			}
		}
		if !hasOllamaDebug {
			logLevel := util.GetDefaultLogLevel()
			var ollamaDebugLevel string
			switch logLevel {
			case "TRACE":
				ollamaDebugLevel = "2"
			case "DEBUG":
				ollamaDebugLevel = "1"
			default:
				ollamaDebugLevel = "0" // INFO, WARNING, ERROR -> no debug
			}
			if ollamaDebugLevel != "0" { // Only set if enabling debug
				env = append(env, corev1.EnvVar{
					Name:  "OLLAMA_DEBUG",
					Value: ollamaDebugLevel,
				})
			}
		}
	}

	// Build volume mounts - add litellm-config for Proxy mode (always uses config file)
	volumeMounts := []corev1.VolumeMount{}
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeProxy && modelapi.Spec.ProxyConfig != nil {
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "litellm-config",
			MountPath: "/etc/litellm",
		})
	}
	// Add ollama-data volume mount for Hosted mode
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted && modelapi.Spec.HostedConfig != nil && modelapi.Spec.HostedConfig.Model != "" {
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
		Env:          env,
		VolumeMounts: volumeMounts,
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

	return container, nil
}

// constructService creates a Service for the ModelAPI
func (r *ModelAPIReconciler) constructService(modelapi *kaosv1alpha1.ModelAPI) *corev1.Service {
	labels := map[string]string{
		"app":      "modelapi",
		"modelapi": modelapi.Name,
	}

	// Use different ports based on mode
	var port int32 = 8000
	var targetPort int32 = 8000
	if modelapi.Spec.Mode == kaosv1alpha1.ModelAPIModeHosted {
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
// Otherwise, generate config from the models list with optional apiKey and apiBase
func (r *ModelAPIReconciler) constructConfigMap(modelapi *kaosv1alpha1.ModelAPI) *corev1.ConfigMap {
	configYaml := ""

	if modelapi.Spec.ProxyConfig != nil {
		if modelapi.Spec.ProxyConfig.ConfigYaml != nil && modelapi.Spec.ProxyConfig.ConfigYaml.FromString != "" {
			// Use user-provided configYaml directly
			configYaml = modelapi.Spec.ProxyConfig.ConfigYaml.FromString
		} else {
			// Generate config from models list (models is required with MinItems=1)
			// Pass merged telemetry config for OTel callback
			telemetry := util.MergeTelemetryConfig(modelapi.Spec.Telemetry)
			configYaml = r.generateLiteLLMConfig(modelapi.Spec.ProxyConfig, telemetry)
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

// generateLiteLLMConfig creates LiteLLM config YAML from ProxyConfig
// The `provider` field determines how models are routed:
// - With provider: model_name: "<model>" → model: "<provider>/<model>"
// - Without provider: model_name: "<model>" → model: "<model>"
// Wildcard handling:
// - models: ["*"] with provider: "nebius" → model_name: "*" → model: "nebius/*"
// - models: ["*"] without provider → model_name: "*" → model: "*"
// When telemetry is enabled, adds OTel callback for traces/metrics.
func (r *ModelAPIReconciler) generateLiteLLMConfig(proxyConfig *kaosv1alpha1.ProxyConfig, telemetry *kaosv1alpha1.TelemetryConfig) string {
	var sb strings.Builder

	sb.WriteString("# Auto-generated LiteLLM config\n")
	sb.WriteString("model_list:\n")

	provider := proxyConfig.Provider

	// Generate model_list entries for each model
	for _, model := range proxyConfig.Models {
		// model_name is what clients request (e.g., "gpt-4o" or "*")
		sb.WriteString(fmt.Sprintf("  - model_name: \"%s\"\n", model))
		sb.WriteString("    litellm_params:\n")

		// model is what LiteLLM uses internally (with provider prefix if set)
		var litellmModel string
		if provider != "" {
			// Prepend provider prefix: "gpt-4o" → "nebius/gpt-4o"
			litellmModel = fmt.Sprintf("%s/%s", provider, model)
		} else {
			// Use model as-is
			litellmModel = model
		}
		sb.WriteString(fmt.Sprintf("      model: \"%s\"\n", litellmModel))

		// Add api_base if configured
		if proxyConfig.APIBase != "" {
			sb.WriteString("      api_base: \"os.environ/PROXY_API_BASE\"\n")
		}

		// Add api_key if configured
		if proxyConfig.APIKey != nil {
			sb.WriteString("      api_key: \"os.environ/PROXY_API_KEY\"\n")
		}
	}

	sb.WriteString("\nlitellm_settings:\n")
	sb.WriteString("  drop_params: true\n")

	// Add OTel callback when telemetry is enabled
	if telemetry != nil && telemetry.Enabled {
		sb.WriteString("  success_callback: [\"otel\"]\n")
		sb.WriteString("  failure_callback: [\"otel\"]\n")
	}

	return sb.String()
}

// SetupWithManager sets up the controller with the Manager.
func (r *ModelAPIReconciler) SetupWithManager(mgr ctrl.Manager) error {
	builder := ctrl.NewControllerManagedBy(mgr).
		For(&kaosv1alpha1.ModelAPI{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ConfigMap{})

	if gateway.GetConfig().Enabled {
		builder = builder.Owns(&gatewayv1.HTTPRoute{})
	}

	return builder.Complete(r)
}

// liteLLMConfig represents the structure of LiteLLM config for validation
type liteLLMConfig struct {
	ModelList []struct {
		ModelName string `yaml:"model_name"`
	} `yaml:"model_list"`
}

// validateConfigYamlModels validates that model_names in configYaml match the models list
func (r *ModelAPIReconciler) validateConfigYamlModels(proxyConfig *kaosv1alpha1.ProxyConfig) error {
	if proxyConfig.ConfigYaml == nil || proxyConfig.ConfigYaml.FromString == "" {
		return nil
	}

	// Parse the configYaml
	var config liteLLMConfig
	if err := yaml.Unmarshal([]byte(proxyConfig.ConfigYaml.FromString), &config); err != nil {
		return fmt.Errorf("failed to parse configYaml: %w", err)
	}

	// Build a set of allowed models from the models list
	allowedModels := make(map[string]bool)
	for _, model := range proxyConfig.Models {
		allowedModels[model] = true
	}

	// Check each model_name in configYaml against the models list
	for _, entry := range config.ModelList {
		if !r.modelMatchesPatterns(entry.ModelName, proxyConfig.Models) {
			return fmt.Errorf("model_name %q in configYaml not found in models list %v", entry.ModelName, proxyConfig.Models)
		}
	}

	return nil
}

// modelMatchesPatterns checks if a model matches any pattern in the list
func (r *ModelAPIReconciler) modelMatchesPatterns(model string, patterns []string) bool {
	for _, pattern := range patterns {
		// Full wildcard
		if pattern == "*" {
			return true
		}
		// Exact match
		if pattern == model {
			return true
		}
		// Provider wildcard: "openai/*" matches "openai/gpt-4"
		if strings.HasSuffix(pattern, "/*") {
			prefix := strings.TrimSuffix(pattern, "*")
			if strings.HasPrefix(model, prefix) {
				return true
			}
		}
	}
	return false
}
