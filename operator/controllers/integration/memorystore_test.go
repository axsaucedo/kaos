package integration

import (
	"context"
	"fmt"
	"sync/atomic"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	policyv1 "k8s.io/api/policy/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func uniqueMemoryStoreName(base string) string {
	return fmt.Sprintf("%s-%d-%d", base, time.Now().UnixNano()%100000, atomic.AddUint64(&nameCounter, 1))
}

func int32Ptr(v int32) *int32 { return &v }

// createReadyModelAPI creates a Proxy ModelAPI and drives it to Ready by marking
// its underlying Deployment available, mirroring real cluster behaviour in envtest.
func createReadyModelAPI(ctx context.Context, namespace, name string) *kaosv1alpha1.ModelAPI {
	modelAPI := &kaosv1alpha1.ModelAPI{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: kaosv1alpha1.ModelAPISpec{
			Mode:        kaosv1alpha1.ModelAPIModeProxy,
			ProxyConfig: &kaosv1alpha1.ProxyConfig{Models: []string{"mock-model", "mock-embed"}},
		},
	}
	Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())

	deployment := &appsv1.Deployment{}
	Eventually(func() error {
		return k8sClient.Get(ctx, types.NamespacedName{
			Name:      fmt.Sprintf("modelapi-%s", name),
			Namespace: namespace,
		}, deployment)
	}, timeout, interval).Should(Succeed())

	deployment.Status.Replicas = 1
	deployment.Status.ReadyReplicas = 1
	deployment.Status.AvailableReplicas = 1
	Expect(k8sClient.Status().Update(ctx, deployment)).To(Succeed())

	Eventually(func() bool {
		updated := &kaosv1alpha1.ModelAPI{}
		if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated); err != nil {
			return false
		}
		return updated.Status.Ready
	}, timeout, interval).Should(BeTrue())

	return modelAPI
}

var _ = Describe("MemoryStore Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should deploy the memory service in local mode with storage, model, and operational env", func() {
		modelAPIName := uniqueMemoryStoreName("mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		name := uniqueMemoryStoreName("local-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Engine: "mem0",
				Storage: kaosv1alpha1.MemoryStorage{
					Type: kaosv1alpha1.MemoryStorageLocal,
					Local: &kaosv1alpha1.LocalMemoryStorage{
						Provider:         "chroma",
						PersistentVolume: &kaosv1alpha1.MemoryPersistentVolume{Size: "2Gi"},
					},
				},
				Replicas: int32Ptr(1),
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
				LongTerm: &kaosv1alpha1.MemoryLongTermConfig{
					Extraction: &kaosv1alpha1.MemoryExtractionConfig{
						Concurrency:  int32Ptr(3),
						SystemPrompt: "only extract deployment facts",
					},
				},
				MediumTerm:         &kaosv1alpha1.MemoryMediumTermConfig{SystemPrompt: "fold tersely"},
				DefaultFailureMode: "strict",
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		// Deployment is created with the memory-service image and correct env.
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("memorystore-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		Expect(deployment.Spec.Template.Spec.Containers).To(HaveLen(1))
		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Image).To(Equal("axsauze/kaos-memory-service:test"))

		envMap := map[string]string{}
		for _, e := range container.Env {
			envMap[e.Name] = e.Value
		}
		Expect(envMap["KAOS_MEMORY_STORAGE_TYPE"]).To(Equal("local"))
		Expect(envMap["KAOS_MEMORY_LOCAL_PATH"]).To(Equal("/data/memory"))
		Expect(envMap["KAOS_MEMORY_SUMMARIZATION_MODEL"]).To(Equal("mock-model"))
		Expect(envMap["KAOS_MEMORY_EMBEDDING_MODEL"]).To(Equal("mock-embed"))
		Expect(envMap["KAOS_MEMORY_MODEL_BASE_URL"]).To(HaveSuffix("/v1"))
		Expect(envMap["KAOS_MEMORY_EXTRACTION_CONCURRENCY"]).To(Equal("3"))
		Expect(envMap["KAOS_MEMORY_EXTRACTION_SYSTEM_PROMPT"]).To(Equal("only extract deployment facts"))
		Expect(envMap["KAOS_MEMORY_SUMMARIZATION_SYSTEM_PROMPT"]).To(Equal("fold tersely"))
		Expect(envMap["KAOS_MEMORY_DEFAULT_FAILURE_MODE"]).To(Equal("strict"))

		// Single-replica local store stays at one replica with no PodDisruptionBudget.
		Expect(deployment.Spec.Replicas).NotTo(BeNil())
		Expect(*deployment.Spec.Replicas).To(Equal(int32(1)))
		Consistently(func() bool {
			err := k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, &policyv1.PodDisruptionBudget{})
			return err != nil
		}, "2s", interval).Should(BeTrue())

		// Volume mount and probes.
		Expect(container.VolumeMounts).To(HaveLen(1))
		Expect(container.VolumeMounts[0].MountPath).To(Equal("/data/memory"))
		Expect(container.ReadinessProbe.HTTPGet.Path).To(Equal("/readyz"))
		Expect(container.LivenessProbe.HTTPGet.Path).To(Equal("/healthz"))

		// Owner reference points back to the MemoryStore.
		Expect(deployment.OwnerReferences).To(HaveLen(1))
		Expect(deployment.OwnerReferences[0].Kind).To(Equal("MemoryStore"))

		// Service is created on the memory service port.
		service := &corev1.Service{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("memorystore-%s", name),
				Namespace: namespace,
			}, service)
		}, timeout, interval).Should(Succeed())
		Expect(service.Spec.Ports[0].Port).To(Equal(int32(8080)))

		// PVC is created in local mode with the requested size.
		pvc := &corev1.PersistentVolumeClaim{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("memorystore-%s-data", name),
				Namespace: namespace,
			}, pvc)
		}, timeout, interval).Should(Succeed())
		Expect(pvc.Spec.Resources.Requests.Storage().String()).To(Equal("2Gi"))

		// Marking the deployment available drives the store to Ready with an endpoint.
		Eventually(func() error {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment); err != nil {
				return err
			}
			deployment.Status.Replicas = 1
			deployment.Status.ReadyReplicas = 1
			deployment.Status.AvailableReplicas = 1
			return k8sClient.Status().Update(ctx, deployment)
		}, timeout, interval).Should(Succeed())

		Eventually(func() bool {
			updated := &kaosv1alpha1.MemoryStore{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated); err != nil {
				return false
			}
			return updated.Status.Ready && updated.Status.Phase == "Ready" &&
				updated.Status.Endpoint == fmt.Sprintf("http://memorystore-%s.%s.svc.cluster.local:8080", name, namespace)
		}, timeout, interval).Should(BeTrue())
	})

	It("defaults the local storage block so only the type is required", func() {
		modelAPIName := uniqueMemoryStoreName("mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		name := uniqueMemoryStoreName("defaulted-store")
		// No Local block at all: type local alone must be valid and provision the
		// PVC at the default 5Gi with the local storage env.
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Storage: kaosv1alpha1.MemoryStorage{Type: kaosv1alpha1.MemoryStorageLocal},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
		}, timeout, interval).Should(Succeed())
		envMap := map[string]string{}
		for _, e := range deployment.Spec.Template.Spec.Containers[0].Env {
			envMap[e.Name] = e.Value
		}
		Expect(envMap["KAOS_MEMORY_STORAGE_TYPE"]).To(Equal("local"))

		pvc := &corev1.PersistentVolumeClaim{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s-data", name), Namespace: namespace}, pvc)
		}, timeout, interval).Should(Succeed())
		Expect(pvc.Spec.Resources.Requests.Storage().String()).To(Equal("5Gi"))
	})

	It("applies telemetry env and container resource overrides on the deployment", func() {
		modelAPIName := uniqueMemoryStoreName("mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		name := uniqueMemoryStoreName("telemetry-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Storage: kaosv1alpha1.MemoryStorage{Type: kaosv1alpha1.MemoryStorageLocal},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
				Telemetry: &kaosv1alpha1.TelemetryConfig{
					Enabled:  true,
					Endpoint: "http://otel-collector.observability:4317",
				},
				Container: &kaosv1alpha1.ContainerOverride{
					Env: []corev1.EnvVar{{Name: "EXTRA_FLAG", Value: "on"}},
					Resources: &corev1.ResourceRequirements{
						Limits: corev1.ResourceList{corev1.ResourceMemory: resource.MustParse("512Mi")},
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
		}, timeout, interval).Should(Succeed())

		container := deployment.Spec.Template.Spec.Containers[0]
		envMap := map[string]string{}
		for _, e := range container.Env {
			envMap[e.Name] = e.Value
		}
		Expect(envMap["OTEL_SERVICE_NAME"]).To(Equal(fmt.Sprintf("memorystore-%s", name)))
		Expect(envMap["OTEL_EXPORTER_OTLP_ENDPOINT"]).To(Equal("http://otel-collector.observability:4317"))
		Expect(envMap["EXTRA_FLAG"]).To(Equal("on"))
		Expect(container.Resources.Limits.Memory().String()).To(Equal("512Mi"))
	})

	It("should wire the external DSN secret and embedding dimensionality in external mode", func() {
		modelAPIName := uniqueMemoryStoreName("mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		secretName := uniqueMemoryStoreName("pgvector-secret")
		secret := &corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{Name: secretName, Namespace: namespace},
			StringData: map[string]string{"dsn": "postgresql://user:pass@pg:5432/mem"},
		}
		Expect(k8sClient.Create(ctx, secret)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, secret) }()

		name := uniqueMemoryStoreName("external-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Engine: "mem0",
				Storage: kaosv1alpha1.MemoryStorage{
					Type: kaosv1alpha1.MemoryStorageExternal,
					External: &kaosv1alpha1.ExternalMemoryStorage{
						Provider: "pgvector",
						ConnectionSecretRef: &corev1.SecretKeySelector{
							LocalObjectReference: corev1.LocalObjectReference{Name: secretName},
							Key:                  "dsn",
						},
						EmbeddingDims: int32Ptr(1536),
						Collection:    "shared-col",
					},
				},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("memorystore-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		container := deployment.Spec.Template.Spec.Containers[0]
		envMap := map[string]string{}
		var dsnEnv *corev1.EnvVar
		for i := range container.Env {
			e := container.Env[i]
			envMap[e.Name] = e.Value
			if e.Name == "KAOS_MEMORY_EXTERNAL_DSN" {
				dsnEnv = &container.Env[i]
			}
		}
		Expect(envMap["KAOS_MEMORY_STORAGE_TYPE"]).To(Equal("external"))
		Expect(envMap["KAOS_MEMORY_EXTERNAL_DIMS"]).To(Equal("1536"))
		Expect(envMap["KAOS_MEMORY_EXTERNAL_COLLECTION"]).To(Equal("shared-col"))

		// The DSN is sourced from the secret key, not rendered as a literal value.
		Expect(dsnEnv).NotTo(BeNil())
		Expect(dsnEnv.Value).To(BeEmpty())
		Expect(dsnEnv.ValueFrom).NotTo(BeNil())
		Expect(dsnEnv.ValueFrom.SecretKeyRef).NotTo(BeNil())
		Expect(dsnEnv.ValueFrom.SecretKeyRef.Name).To(Equal(secretName))
		Expect(dsnEnv.ValueFrom.SecretKeyRef.Key).To(Equal("dsn"))

		// External stores default to two replicas guarded by a PodDisruptionBudget.
		Expect(deployment.Spec.Replicas).NotTo(BeNil())
		Expect(*deployment.Spec.Replicas).To(Equal(int32(2)))

		pdb := &policyv1.PodDisruptionBudget{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, pdb)
		}, timeout, interval).Should(Succeed())
		Expect(pdb.Spec.MinAvailable).NotTo(BeNil())
		Expect(pdb.Spec.MinAvailable.IntValue()).To(Equal(1))

		// No PVC is provisioned in external mode.
		pvc := &corev1.PersistentVolumeClaim{}
		Consistently(func() bool {
			err := k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s-data", name), Namespace: namespace}, pvc)
			return err != nil
		}, "2s", interval).Should(BeTrue())
	})

	It("projects the conversational tier fields onto env with container.env overrides winning", func() {
		modelAPIName := uniqueMemoryStoreName("mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		boolPtr := func(v bool) *bool { return &v }
		floatPtr := func(v float64) *float64 { return &v }

		name := uniqueMemoryStoreName("tier-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Storage: kaosv1alpha1.MemoryStorage{
					Type:  kaosv1alpha1.MemoryStorageLocal,
					Local: &kaosv1alpha1.LocalMemoryStorage{Collection: "support-col"},
				},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
				ShortTerm: &kaosv1alpha1.MemoryShortTermConfig{
					TokenBudget:  int32Ptr(64),
					HardEventCap: int32Ptr(10),
				},
				MediumTerm: &kaosv1alpha1.MemoryMediumTermConfig{
					Enabled:           boolPtr(true),
					CompactionTrigger: int32Ptr(48),
					CompactionTarget:  int32Ptr(24),
					DigestRetention:   int32Ptr(5),
					SystemPrompt:      "fold tersely",
				},
				LongTerm: &kaosv1alpha1.MemoryLongTermConfig{
					Enabled:        boolPtr(true),
					DefaultTopK:    int32Ptr(5),
					ScoreThreshold: floatPtr(0.4),
					Rerank:         boolPtr(true),
					Extraction: &kaosv1alpha1.MemoryExtractionConfig{
						Concurrency:  int32Ptr(3),
						MaxRetries:   int32Ptr(1),
						SystemPrompt: "only extract deployment facts",
					},
				},
				RequestConcurrency: int32Ptr(4),
				Container: &kaosv1alpha1.ContainerOverride{
					Env: []corev1.EnvVar{{Name: "KAOS_MEMORY_TOKEN_BUDGET", Value: "128"}},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
		}, timeout, interval).Should(Succeed())

		// The env map keeps the last occurrence of a name, mirroring how the kubelet
		// resolves duplicates: the container.env override must win over the projection.
		env := deployment.Spec.Template.Spec.Containers[0].Env
		envMap := map[string]string{}
		for _, e := range env {
			envMap[e.Name] = e.Value
		}
		Expect(envMap["KAOS_MEMORY_LOCAL_COLLECTION"]).To(Equal("support-col"))
		Expect(envMap["KAOS_MEMORY_HARD_EVENT_CAP"]).To(Equal("10"))
		Expect(envMap["KAOS_MEMORY_ROLLING_SUMMARY"]).To(Equal("true"))
		Expect(envMap["KAOS_MEMORY_COMPACTION_TRIGGER"]).To(Equal("48"))
		Expect(envMap["KAOS_MEMORY_COMPACTION_TARGET"]).To(Equal("24"))
		Expect(envMap["KAOS_MEMORY_DIGEST_RETENTION"]).To(Equal("5"))
		Expect(envMap["KAOS_MEMORY_SUMMARIZATION_SYSTEM_PROMPT"]).To(Equal("fold tersely"))
		Expect(envMap["KAOS_MEMORY_LONG_TERM_ENABLED"]).To(Equal("true"))
		Expect(envMap["KAOS_MEMORY_DEFAULT_TOP_K"]).To(Equal("5"))
		Expect(envMap["KAOS_MEMORY_SCORE_THRESHOLD"]).To(Equal("0.4"))
		Expect(envMap["KAOS_MEMORY_RERANK"]).To(Equal("true"))
		Expect(envMap["KAOS_MEMORY_EXTRACTION_CONCURRENCY"]).To(Equal("3"))
		Expect(envMap["KAOS_MEMORY_EXTRACTION_MAX_RETRIES"]).To(Equal("1"))
		Expect(envMap["KAOS_MEMORY_EXTRACTION_SYSTEM_PROMPT"]).To(Equal("only extract deployment facts"))
		Expect(envMap["KAOS_MEMORY_REQUEST_CONCURRENCY"]).To(Equal("4"))

		// The projected token budget appears before the explicit container.env
		// override, so the override wins.
		Expect(envMap["KAOS_MEMORY_TOKEN_BUDGET"]).To(Equal("128"))
		values := []string{}
		for _, e := range env {
			if e.Name == "KAOS_MEMORY_TOKEN_BUDGET" {
				values = append(values, e.Value)
			}
		}
		Expect(values).To(Equal([]string{"64", "128"}))
	})

	It("projects no tier env when the tier blocks are absent", func() {
		modelAPIName := uniqueMemoryStoreName("mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		name := uniqueMemoryStoreName("untuned-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Storage: kaosv1alpha1.MemoryStorage{Type: kaosv1alpha1.MemoryStorageLocal},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
		}, timeout, interval).Should(Succeed())

		for _, e := range deployment.Spec.Template.Spec.Containers[0].Env {
			Expect(e.Name).NotTo(BeElementOf(
				"KAOS_MEMORY_TOKEN_BUDGET", "KAOS_MEMORY_HARD_EVENT_CAP",
				"KAOS_MEMORY_ROLLING_SUMMARY", "KAOS_MEMORY_COMPACTION_TRIGGER",
				"KAOS_MEMORY_COMPACTION_TARGET", "KAOS_MEMORY_DIGEST_RETENTION",
				"KAOS_MEMORY_SUMMARIZATION_SYSTEM_PROMPT", "KAOS_MEMORY_LONG_TERM_ENABLED",
				"KAOS_MEMORY_DEFAULT_TOP_K", "KAOS_MEMORY_SCORE_THRESHOLD",
				"KAOS_MEMORY_RERANK", "KAOS_MEMORY_EXTRACTION_CONCURRENCY",
				"KAOS_MEMORY_EXTRACTION_MAX_RETRIES", "KAOS_MEMORY_EXTRACTION_SYSTEM_PROMPT",
				"KAOS_MEMORY_REQUEST_CONCURRENCY", "KAOS_MEMORY_LOCAL_COLLECTION",
			))
		}
	})

	It("rejects compaction marks the memory service would reject", func() {
		base := func(name string) *kaosv1alpha1.MemoryStore {
			return &kaosv1alpha1.MemoryStore{
				ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
				Spec: kaosv1alpha1.MemoryStoreSpec{
					Storage: kaosv1alpha1.MemoryStorage{Type: kaosv1alpha1.MemoryStorageLocal},
					Models: kaosv1alpha1.MemoryModels{
						Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: "m", Model: "mock-model"},
						Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: "m", Model: "mock-embed"},
					},
				},
			}
		}

		// target >= trigger is rejected at admission, mirroring the service invariant.
		invalid := base(uniqueMemoryStoreName("cel-target"))
		invalid.Spec.MediumTerm = &kaosv1alpha1.MemoryMediumTermConfig{
			CompactionTrigger: int32Ptr(100),
			CompactionTarget:  int32Ptr(100),
		}
		Expect(k8sClient.Create(ctx, invalid)).NotTo(Succeed())

		// trigger > tokenBudget is rejected.
		invalid = base(uniqueMemoryStoreName("cel-trigger"))
		invalid.Spec.ShortTerm = &kaosv1alpha1.MemoryShortTermConfig{TokenBudget: int32Ptr(64)}
		invalid.Spec.MediumTerm = &kaosv1alpha1.MemoryMediumTermConfig{CompactionTrigger: int32Ptr(100)}
		Expect(k8sClient.Create(ctx, invalid)).NotTo(Succeed())

		// tokenBudget=1 derives target=1 and trigger=1 (target < trigger fails),
		// exactly as ShortTermTierConfig rejects it at startup.
		invalid = base(uniqueMemoryStoreName("cel-budget"))
		invalid.Spec.ShortTerm = &kaosv1alpha1.MemoryShortTermConfig{TokenBudget: int32Ptr(1)}
		Expect(k8sClient.Create(ctx, invalid)).NotTo(Succeed())

		// 0-valued marks derive from the budget and pass, as the service accepts them.
		valid := base(uniqueMemoryStoreName("cel-valid"))
		valid.Spec.ShortTerm = &kaosv1alpha1.MemoryShortTermConfig{TokenBudget: int32Ptr(64)}
		valid.Spec.MediumTerm = &kaosv1alpha1.MemoryMediumTermConfig{
			Enabled:           func(v bool) *bool { return &v }(true),
			CompactionTrigger: int32Ptr(0),
			CompactionTarget:  int32Ptr(0),
		}
		Expect(k8sClient.Create(ctx, valid)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, valid) }()
	})

	It("accepts maxReadScope user regardless of identity posture", func() {
		name := uniqueMemoryStoreName("user-scope-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Storage: kaosv1alpha1.MemoryStorage{Type: kaosv1alpha1.MemoryStorageLocal},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: "m", Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: "m", Model: "mock-embed"},
				},
				MaxReadScope: "user",
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		// The ceiling grants permission and performs no reads, so it needs no
		// posture; the store proceeds normally (held Pending here on the
		// unresolved ModelAPI). Rejecting a user ceiling without user identity
		// happens on the claiming Agent, never on the store.
		getPhase := func() string {
			updated := &kaosv1alpha1.MemoryStore{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated); err != nil {
				return ""
			}
			return updated.Status.Phase
		}
		Eventually(getPhase, timeout, interval).Should(Equal("Pending"))
		Consistently(getPhase, "2s", interval).ShouldNot(Equal("Failed"))
	})

	It("should hold Pending until the referenced ModelAPIs are ready", func() {
		name := uniqueMemoryStoreName("pending-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Engine: "mem0",
				Storage: kaosv1alpha1.MemoryStorage{
					Type:  kaosv1alpha1.MemoryStorageLocal,
					Local: &kaosv1alpha1.LocalMemoryStorage{Provider: "chroma"},
				},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: "missing-model", Model: "m"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: "missing-model", Model: "e"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		// With a missing ModelAPI the store stays Pending and no Deployment is created.
		Eventually(func() string {
			updated := &kaosv1alpha1.MemoryStore{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated); err != nil {
				return ""
			}
			return updated.Status.Phase
		}, timeout, interval).Should(Equal("Pending"))

		Consistently(func() bool {
			deployment := &appsv1.Deployment{}
			err := k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
			return err != nil
		}, "2s", interval).Should(BeTrue())

		// Once the ModelAPI becomes ready, the store proceeds to create the Deployment.
		modelAPI := createReadyModelAPI(ctx, namespace, "missing-model")
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
		}, timeout, interval).Should(Succeed())
	})
})
