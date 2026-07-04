package integration

import (
	"context"
	"fmt"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func uniqueMemoryStoreName(base string) string {
	return fmt.Sprintf("%s-%d", base, time.Now().UnixNano()%100000)
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
				Extraction:         &kaosv1alpha1.MemoryExtractionConfig{Concurrency: int32Ptr(3)},
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
		Expect(envMap["KAOS_MEMORY_DEFAULT_FAILURE_MODE"]).To(Equal("strict"))

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
})
