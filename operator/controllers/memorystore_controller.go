package controllers

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/go-logr/logr"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	policyv1 "k8s.io/api/policy/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
	"github.com/axsaucedo/kaos/operator/pkg/security"
	"github.com/axsaucedo/kaos/operator/pkg/util"
)

// memoryServicePort is the container/service port the memory service listens on.
const memoryServicePort = 8080

// memoryDataPath is the in-container mount path for the local-mode PersistentVolume.
const memoryDataPath = "/data/memory"

// MemoryStoreReconciler reconciles a MemoryStore object into the memory service.
type MemoryStoreReconciler struct {
	client.Client
	Log    logr.Logger
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=kaos.tools,resources=memorystores,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=kaos.tools,resources=memorystores/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=policy,resources=poddisruptionbudgets,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups="",resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete

// Reconcile moves a MemoryStore toward its desired state by deploying and
// operating the memory service.
func (r *MemoryStoreReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	store := &kaosv1alpha1.MemoryStore{}
	if err := r.Get(ctx, req.NamespacedName, store); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Set initial status.
	if store.Status.Phase == "" {
		store.Status.Phase = "Pending"
		store.Status.Ready = false
		if err := r.Status().Update(ctx, store); err != nil {
			log.Error(err, "failed to update status")
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	}

	// Resolve and ready-gate the referenced ModelAPIs before deploying.
	modelEnv, requeue, err := r.resolveModelEnv(ctx, store)
	if err != nil {
		return ctrl.Result{}, err
	}
	if requeue {
		return ctrl.Result{RequeueAfter: time.Second * 5}, nil
	}

	// Provision the PersistentVolumeClaim in local mode.
	if store.Spec.Storage.Type == kaosv1alpha1.MemoryStorageLocal {
		if err := r.reconcilePVC(ctx, store); err != nil {
			log.Error(err, "failed to reconcile PersistentVolumeClaim")
			return ctrl.Result{}, err
		}
	}

	// Create or update the Deployment.
	deployment, err := r.reconcileDeployment(ctx, store, modelEnv)
	if err != nil {
		log.Error(err, "failed to reconcile Deployment")
		store.Status.Phase = "Failed"
		store.Status.Message = fmt.Sprintf("Failed to reconcile Deployment: %v", err)
		r.Status().Update(ctx, store)
		return ctrl.Result{}, err
	}

	// Create the Service.
	serviceName := memoryStoreResourceName(store.Name)
	if err := r.reconcileService(ctx, store); err != nil {
		log.Error(err, "failed to reconcile Service")
		store.Status.Phase = "Failed"
		store.Status.Message = fmt.Sprintf("Failed to reconcile Service: %v", err)
		r.Status().Update(ctx, store)
		return ctrl.Result{}, err
	}

	// Guard availability of multi-replica external stores with a PodDisruptionBudget
	// so voluntary disruptions cannot drain the stateless fleet below one Pod.
	if err := r.reconcilePodDisruptionBudget(ctx, store); err != nil {
		log.Error(err, "failed to reconcile PodDisruptionBudget")
		store.Status.Phase = "Failed"
		store.Status.Message = fmt.Sprintf("Failed to reconcile PodDisruptionBudget: %v", err)
		r.Status().Update(ctx, store)
		return ctrl.Result{}, err
	}

	// Route the memory service through the gateway data-plane and guard it with a
	// default-deny NetworkPolicy so agents cannot bypass the gateway to reach it
	// directly. Memory is internal-only (no external clients), but the same
	// gateway path carries the identity headers scope enforcement relies on.
	r.reconcileGatewayAndSecurity(ctx, store, serviceName, log)

	// Update status endpoint and readiness.
	store.Status.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local:%d", serviceName, store.Namespace, memoryServicePort)
	store.Status.Deployment = util.CopyDeploymentStatus(deployment)
	if deployment.Status.ReadyReplicas > 0 {
		store.Status.Ready = true
		store.Status.Phase = "Ready"
	} else {
		store.Status.Ready = false
		store.Status.Phase = "Pending"
	}
	store.Status.Message = fmt.Sprintf("Deployment ready replicas: %d/%d", deployment.Status.ReadyReplicas, *deployment.Spec.Replicas)

	if err := r.Status().Update(ctx, store); err != nil {
		log.Error(err, "failed to update status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// resolveModelEnv resolves the summarization and embedding ModelAPI references and
// returns the model-related environment for the service. When a reference is
// missing or not ready it holds the store Pending and signals a requeue.
func (r *MemoryStoreReconciler) resolveModelEnv(ctx context.Context, store *kaosv1alpha1.MemoryStore) ([]corev1.EnvVar, bool, error) {
	log := log.FromContext(ctx)

	summarization := &kaosv1alpha1.ModelAPI{}
	sumRef := store.Spec.Models.Summarization
	if err := r.Get(ctx, types.NamespacedName{Name: sumRef.ModelAPI, Namespace: store.Namespace}, summarization); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, true, r.holdPending(ctx, store, fmt.Sprintf("summarization ModelAPI %q not found", sumRef.ModelAPI))
		}
		return nil, false, err
	}
	if !summarization.Status.Ready {
		return nil, true, r.holdPending(ctx, store, fmt.Sprintf("summarization ModelAPI %q is not ready", sumRef.ModelAPI))
	}

	embedding := &kaosv1alpha1.ModelAPI{}
	embRef := store.Spec.Models.Embedding
	if err := r.Get(ctx, types.NamespacedName{Name: embRef.ModelAPI, Namespace: store.Namespace}, embedding); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, true, r.holdPending(ctx, store, fmt.Sprintf("embedding ModelAPI %q not found", embRef.ModelAPI))
		}
		return nil, false, err
	}
	if !embedding.Status.Ready {
		return nil, true, r.holdPending(ctx, store, fmt.Sprintf("embedding ModelAPI %q is not ready", embRef.ModelAPI))
	}

	// Both model roles are served through a single OpenAI-compatible base URL; the
	// summarization ModelAPI endpoint drives it and both must be served there.
	baseURL := fmt.Sprintf("%s/v1", summarization.Status.Endpoint)
	log.Info("resolved memory model endpoints", "baseURL", baseURL,
		"summarizationModel", sumRef.Model, "embeddingModel", embRef.Model)

	return []corev1.EnvVar{
		{Name: "KAOS_MEMORY_MODEL_BASE_URL", Value: baseURL},
		{Name: "KAOS_MEMORY_SUMMARIZATION_MODEL", Value: sumRef.Model},
		{Name: "KAOS_MEMORY_EMBEDDING_MODEL", Value: embRef.Model},
	}, false, nil
}

// holdPending records a Pending status with a human-readable reason.
func (r *MemoryStoreReconciler) holdPending(ctx context.Context, store *kaosv1alpha1.MemoryStore, message string) error {
	store.Status.Phase = "Pending"
	store.Status.Ready = false
	store.Status.Message = message
	if err := r.Status().Update(ctx, store); err != nil {
		return err
	}
	return nil
}

// reconcilePVC ensures the local-mode PersistentVolumeClaim exists.
func (r *MemoryStoreReconciler) reconcilePVC(ctx context.Context, store *kaosv1alpha1.MemoryStore) error {
	log := log.FromContext(ctx)
	pvcName := memoryStorePVCName(store.Name)

	pvc := &corev1.PersistentVolumeClaim{}
	err := r.Get(ctx, types.NamespacedName{Name: pvcName, Namespace: store.Namespace}, pvc)
	if err == nil {
		// PVCs are immutable in the fields we manage; leave existing claims untouched.
		return nil
	}
	if !apierrors.IsNotFound(err) {
		return err
	}

	size := "5Gi"
	if local := store.Spec.Storage.Local; local != nil && local.PersistentVolume != nil && local.PersistentVolume.Size != "" {
		size = local.PersistentVolume.Size
	}
	quantity, err := resource.ParseQuantity(size)
	if err != nil {
		return fmt.Errorf("invalid persistentVolume.size %q: %w", size, err)
	}

	pvc = &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      pvcName,
			Namespace: store.Namespace,
			Labels:    memoryStoreLabels(store.Name),
		},
		Spec: corev1.PersistentVolumeClaimSpec{
			AccessModes: []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
			Resources: corev1.VolumeResourceRequirements{
				Requests: corev1.ResourceList{corev1.ResourceStorage: quantity},
			},
		},
	}
	if err := controllerutil.SetControllerReference(store, pvc, r.Scheme); err != nil {
		return err
	}
	log.Info("Creating PersistentVolumeClaim", "name", pvcName)
	return r.Create(ctx, pvc)
}

// reconcileDeployment creates or updates the memory-service Deployment.
func (r *MemoryStoreReconciler) reconcileDeployment(ctx context.Context, store *kaosv1alpha1.MemoryStore, modelEnv []corev1.EnvVar) (*appsv1.Deployment, error) {
	log := log.FromContext(ctx)
	name := memoryStoreResourceName(store.Name)

	desired, err := r.constructDeployment(store, modelEnv)
	if err != nil {
		return nil, err
	}
	if err := controllerutil.SetControllerReference(store, desired, r.Scheme); err != nil {
		return nil, err
	}

	existing := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: name, Namespace: store.Namespace}, existing)
	if err != nil && apierrors.IsNotFound(err) {
		log.Info("Creating Deployment", "name", name)
		if err := r.Create(ctx, desired); err != nil {
			return nil, err
		}
		return desired, nil
	} else if err != nil {
		return nil, err
	}

	currentHash := existing.Spec.Template.Annotations[util.PodSpecHashAnnotation]
	desiredHash := desired.Spec.Template.Annotations[util.PodSpecHashAnnotation]
	if currentHash != desiredHash {
		log.Info("Updating Deployment due to spec change", "name", name)
		existing.Spec = desired.Spec
		if err := r.Update(ctx, existing); err != nil {
			return nil, err
		}
	}
	return existing, nil
}

// constructDeployment builds the memory-service Deployment for the store.
func (r *MemoryStoreReconciler) constructDeployment(store *kaosv1alpha1.MemoryStore, modelEnv []corev1.EnvVar) (*appsv1.Deployment, error) {
	image := os.Getenv("DEFAULT_MEMORY_SERVICE_IMAGE")
	if store.Spec.Container != nil && store.Spec.Container.Image != "" {
		image = store.Spec.Container.Image
	}
	if image == "" {
		return nil, fmt.Errorf("DEFAULT_MEMORY_SERVICE_IMAGE environment variable is required but not set")
	}

	labels := memoryStoreLabels(store.Name)
	replicas := memoryStoreReplicas(store)

	env, volumes, mounts := r.buildStorageEnv(store)
	env = append(env, modelEnv...)
	env = append(env, r.buildOperationalEnv(store)...)
	env = append(env, util.BuildTelemetryEnvVars(util.MergeTelemetryConfig(store.Spec.Telemetry), memoryStoreResourceName(store.Name), store.Namespace)...)
	if store.Spec.Container != nil {
		env = append(env, store.Spec.Container.Env...)
	}

	container := corev1.Container{
		Name:            "memory",
		Image:           image,
		ImagePullPolicy: corev1.PullIfNotPresent,
		Ports: []corev1.ContainerPort{
			{Name: "http", ContainerPort: memoryServicePort, Protocol: corev1.ProtocolTCP},
		},
		Env:          env,
		VolumeMounts: mounts,
		LivenessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{Path: "/healthz", Port: intstr.FromInt(memoryServicePort)},
			},
			InitialDelaySeconds: 10,
			PeriodSeconds:       15,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{Path: "/readyz", Port: intstr.FromInt(memoryServicePort)},
			},
			InitialDelaySeconds: 5,
			PeriodSeconds:       10,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		},
	}
	if c := store.Spec.Container; c != nil {
		if len(c.Command) > 0 {
			container.Command = c.Command
		}
		if len(c.Args) > 0 {
			container.Args = c.Args
		}
		if c.Resources != nil {
			container.Resources = *c.Resources
		}
	}

	podSpec := corev1.PodSpec{
		Containers: []corev1.Container{container},
		Volumes:    volumes,
	}
	podSpecHash := util.ComputePodSpecHash(podSpec)

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      memoryStoreResourceName(store.Name),
			Namespace: store.Namespace,
			Labels:    labels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: labels},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      labels,
					Annotations: map[string]string{util.PodSpecHashAnnotation: podSpecHash},
				},
				Spec: podSpec,
			},
		},
	}
	return deployment, nil
}

// buildStorageEnv returns the storage-related env, volumes, and mounts for the mode.
func (r *MemoryStoreReconciler) buildStorageEnv(store *kaosv1alpha1.MemoryStore) ([]corev1.EnvVar, []corev1.Volume, []corev1.VolumeMount) {
	if store.Spec.Storage.Type == kaosv1alpha1.MemoryStorageLocal {
		env := []corev1.EnvVar{
			{Name: "KAOS_MEMORY_STORAGE_TYPE", Value: "local"},
			{Name: "KAOS_MEMORY_LOCAL_PATH", Value: memoryDataPath},
		}
		if local := store.Spec.Storage.Local; local != nil && local.Collection != "" {
			env = append(env, corev1.EnvVar{
				Name:  "KAOS_MEMORY_LOCAL_COLLECTION",
				Value: local.Collection,
			})
		}
		volumes := []corev1.Volume{{
			Name: "data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
					ClaimName: memoryStorePVCName(store.Name),
				},
			},
		}}
		mounts := []corev1.VolumeMount{{Name: "data", MountPath: memoryDataPath}}
		return env, volumes, mounts
	}

	// External mode: connect to an external pgvector database. The DSN is sourced
	// from the referenced Secret key and the embedding dimensionality is passed
	// through so the service can provision the vector column.
	env := []corev1.EnvVar{{Name: "KAOS_MEMORY_STORAGE_TYPE", Value: "external"}}
	if ext := store.Spec.Storage.External; ext != nil {
		if ext.ConnectionSecretRef != nil {
			env = append(env, corev1.EnvVar{
				Name:      "KAOS_MEMORY_EXTERNAL_DSN",
				ValueFrom: &corev1.EnvVarSource{SecretKeyRef: ext.ConnectionSecretRef},
			})
		}
		if ext.EmbeddingDims != nil {
			env = append(env, corev1.EnvVar{
				Name:  "KAOS_MEMORY_EXTERNAL_DIMS",
				Value: fmt.Sprintf("%d", *ext.EmbeddingDims),
			})
		}
		if ext.Collection != "" {
			env = append(env, corev1.EnvVar{
				Name:  "KAOS_MEMORY_EXTERNAL_COLLECTION",
				Value: ext.Collection,
			})
		}
	}
	return env, nil, nil
}

// buildOperationalEnv returns the store-level operational knobs: the typed
// conversational-tier fields projected onto their KAOS_MEMORY_* env vars. Only
// set fields are projected, so an absent field leaves the service default in
// place, and explicit container.env entries (appended later) still win.
func (r *MemoryStoreReconciler) buildOperationalEnv(store *kaosv1alpha1.MemoryStore) []corev1.EnvVar {
	var env []corev1.EnvVar
	addInt := func(name string, value *int32) {
		if value != nil {
			env = append(env, corev1.EnvVar{Name: name, Value: fmt.Sprintf("%d", *value)})
		}
	}
	addBool := func(name string, value *bool) {
		if value != nil {
			env = append(env, corev1.EnvVar{Name: name, Value: fmt.Sprintf("%t", *value)})
		}
	}
	addString := func(name, value string) {
		if value != "" {
			env = append(env, corev1.EnvVar{Name: name, Value: value})
		}
	}

	if st := store.Spec.ShortTerm; st != nil {
		addInt("KAOS_MEMORY_TOKEN_BUDGET", st.TokenBudget)
		addInt("KAOS_MEMORY_HARD_EVENT_CAP", st.HardEventCap)
	}
	if mt := store.Spec.MediumTerm; mt != nil {
		addBool("KAOS_MEMORY_ROLLING_SUMMARY", mt.Enabled)
		addInt("KAOS_MEMORY_COMPACTION_TRIGGER", mt.CompactionTrigger)
		addInt("KAOS_MEMORY_COMPACTION_TARGET", mt.CompactionTarget)
		addInt("KAOS_MEMORY_DIGEST_RETENTION", mt.DigestRetention)
		addString("KAOS_MEMORY_SUMMARIZATION_SYSTEM_PROMPT", mt.SystemPrompt)
	}
	if lt := store.Spec.LongTerm; lt != nil {
		addBool("KAOS_MEMORY_LONG_TERM_ENABLED", lt.Enabled)
		addInt("KAOS_MEMORY_DEFAULT_TOP_K", lt.DefaultTopK)
		if lt.ScoreThreshold != nil {
			env = append(env, corev1.EnvVar{
				Name:  "KAOS_MEMORY_SCORE_THRESHOLD",
				Value: strconv.FormatFloat(*lt.ScoreThreshold, 'f', -1, 64),
			})
		}
		addBool("KAOS_MEMORY_RERANK", lt.Rerank)
		if ex := lt.Extraction; ex != nil {
			addInt("KAOS_MEMORY_EXTRACTION_CONCURRENCY", ex.Concurrency)
			addInt("KAOS_MEMORY_EXTRACTION_MAX_RETRIES", ex.MaxRetries)
			addString("KAOS_MEMORY_EXTRACTION_SYSTEM_PROMPT", ex.SystemPrompt)
		}
	}
	addInt("KAOS_MEMORY_REQUEST_CONCURRENCY", store.Spec.RequestConcurrency)
	addString("KAOS_MEMORY_DEFAULT_FAILURE_MODE", store.Spec.DefaultFailureMode)
	return env
}

// reconcileService creates the memory-service Service if absent.
func (r *MemoryStoreReconciler) reconcileService(ctx context.Context, store *kaosv1alpha1.MemoryStore) error {
	log := log.FromContext(ctx)
	name := memoryStoreResourceName(store.Name)

	service := &corev1.Service{}
	err := r.Get(ctx, types.NamespacedName{Name: name, Namespace: store.Namespace}, service)
	if err == nil {
		return nil
	}
	if !apierrors.IsNotFound(err) {
		return err
	}

	labels := memoryStoreLabels(store.Name)
	service = &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: store.Namespace,
			Labels:    labels,
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Ports: []corev1.ServicePort{{
				Name:       "http",
				Port:       memoryServicePort,
				TargetPort: intstr.FromInt(memoryServicePort),
				Protocol:   corev1.ProtocolTCP,
			}},
			Selector: labels,
		},
	}
	if err := controllerutil.SetControllerReference(store, service, r.Scheme); err != nil {
		return err
	}
	log.Info("Creating Service", "name", name)
	return r.Create(ctx, service)
}

// reconcileGatewayAndSecurity wires the memory service into the Gateway API and
// applies the default-deny NetworkPolicy plus gateway policies, mirroring the
// other workloads. Failures are logged but non-fatal: memory routing is an
// augmentation and must not block the store from reporting Ready.
func (r *MemoryStoreReconciler) reconcileGatewayAndSecurity(ctx context.Context, store *kaosv1alpha1.MemoryStore, serviceName string, log logr.Logger) {
	labels := memoryStoreLabels(store.Name)

	timeout := ""
	if store.Spec.GatewayRoute != nil {
		timeout = store.Spec.GatewayRoute.Timeout
	}
	if err := gateway.ReconcileHTTPRoute(ctx, r.Client, r.Scheme, store, gateway.HTTPRouteParams{
		ResourceType: gateway.ResourceTypeMemoryStore,
		ResourceName: store.Name,
		Namespace:    store.Namespace,
		ServiceName:  serviceName,
		ServicePort:  memoryServicePort,
		Labels:       labels,
		Timeout:      timeout,
	}, log); err != nil {
		log.Error(err, "failed to reconcile HTTPRoute")
	}

	secCfg := security.GetConfig()
	if !secCfg.IsOperational() {
		return
	}
	routeName := gateway.HTTPRouteName(gateway.ResourceTypeMemoryStore, store.Name)
	policyParams := security.PolicyParams{
		Name:      routeName,
		Namespace: store.Namespace,
		RouteName: routeName,
		Labels:    labels,
	}
	if err := security.ReconcileSecurityPolicy(ctx, r.Client, r.Scheme, store, policyParams, secCfg, log); err != nil {
		log.Error(err, "failed to reconcile SecurityPolicy")
	}
	// Memory has no external clients, so egress stays namespace-restricted (no
	// AllowExternalEgress) unlike ModelAPI proxies.
	if err := security.ReconcileNetworkPolicy(ctx, r.Client, r.Scheme, store, security.NetworkPolicyParams{
		Name:        routeName,
		Namespace:   store.Namespace,
		PodSelector: labels,
		Labels:      labels,
	}, secCfg, log); err != nil {
		log.Error(err, "failed to reconcile NetworkPolicy")
	}
}

// memoryStoreReplicas resolves the desired replica count. An explicit spec value
// always wins; otherwise external (stateless, shared-Postgres) stores default to
// two replicas for availability while local (single-writer) stores stay at one.
func memoryStoreReplicas(store *kaosv1alpha1.MemoryStore) int32 {
	if store.Spec.Replicas != nil {
		return *store.Spec.Replicas
	}
	if store.Spec.Storage.Type == kaosv1alpha1.MemoryStorageExternal {
		return 2
	}
	return 1
}

// reconcilePodDisruptionBudget ensures a PodDisruptionBudget guards multi-replica
// external stores and is absent for single-replica stores. A PDB pinning
// minAvailable=1 on a single-replica store would block all voluntary evictions,
// so it is only applied when at least two replicas are desired.
func (r *MemoryStoreReconciler) reconcilePodDisruptionBudget(ctx context.Context, store *kaosv1alpha1.MemoryStore) error {
	log := log.FromContext(ctx)
	name := memoryStoreResourceName(store.Name)
	labels := memoryStoreLabels(store.Name)

	existing := &policyv1.PodDisruptionBudget{}
	err := r.Get(ctx, types.NamespacedName{Name: name, Namespace: store.Namespace}, existing)

	if memoryStoreReplicas(store) < 2 {
		// Single-replica store: ensure no PDB lingers from a previous multi-replica spec.
		if err == nil {
			log.Info("Deleting PodDisruptionBudget for single-replica store", "name", name)
			return client.IgnoreNotFound(r.Delete(ctx, existing))
		}
		return client.IgnoreNotFound(err)
	}

	minAvailable := intstr.FromInt(1)
	desired := &policyv1.PodDisruptionBudget{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: store.Namespace,
			Labels:    labels,
		},
		Spec: policyv1.PodDisruptionBudgetSpec{
			MinAvailable: &minAvailable,
			Selector:     &metav1.LabelSelector{MatchLabels: labels},
		},
	}
	if err := controllerutil.SetControllerReference(store, desired, r.Scheme); err != nil {
		return err
	}

	if apierrors.IsNotFound(err) {
		log.Info("Creating PodDisruptionBudget", "name", name)
		return r.Create(ctx, desired)
	} else if err != nil {
		return err
	}

	if existing.Spec.MinAvailable == nil || existing.Spec.MinAvailable.IntValue() != 1 {
		existing.Spec = desired.Spec
		log.Info("Updating PodDisruptionBudget", "name", name)
		return r.Update(ctx, existing)
	}
	return nil
}

func memoryStoreResourceName(name string) string { return fmt.Sprintf("memorystore-%s", name) }

func memoryStorePVCName(name string) string { return fmt.Sprintf("memorystore-%s-data", name) }

func memoryStoreLabels(name string) map[string]string {
	return map[string]string{"app": "memorystore", "memorystore": name}
}

// SetupWithManager sets up the controller with the Manager.
func (r *MemoryStoreReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&kaosv1alpha1.MemoryStore{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.PersistentVolumeClaim{}).
		Owns(&policyv1.PodDisruptionBudget{}).
		Complete(r)
}
