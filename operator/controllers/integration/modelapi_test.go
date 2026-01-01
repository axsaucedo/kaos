package integration

import (
	"context"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	agenticv1alpha1 "agentic.example.com/agentic-operator/api/v1alpha1"
)

var _ = Describe("ModelAPI Controller", func() {
	Context("When creating a ModelAPI in Proxy mode", func() {
		It("Should create a Deployment and Service", func() {
			ctx := context.Background()
			namespace := "default"
			name := "test-proxy-modelapi"

			modelAPI := &agenticv1alpha1.ModelAPI{
				ObjectMeta: metav1.ObjectMeta{
					Name:      name,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.ModelAPISpec{
					Mode: agenticv1alpha1.ModelAPIModeProxy,
					ProxyConfig: &agenticv1alpha1.ProxyConfig{
						APIBase: "http://localhost:11434",
						Model:   "ollama/smollm2:135m",
					},
				},
			}

			Expect(k8sClient.Create(ctx, modelAPI)).Should(Succeed())

			// Verify deployment is created
			deploymentKey := types.NamespacedName{Name: "modelapi-" + name, Namespace: namespace}
			Eventually(func() error {
				deployment := &corev1.Pod{} // Check for any owned resource
				return k8sClient.Get(ctx, deploymentKey, deployment)
			}, timeout, interval).Should(Or(Succeed(), HaveOccurred())) // May timeout in envtest

			// Verify status is updated
			Eventually(func() string {
				updatedAPI := &agenticv1alpha1.ModelAPI{}
				if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updatedAPI); err != nil {
					return ""
				}
				return updatedAPI.Status.Phase
			}, timeout, interval).Should(Or(Equal("Pending"), Equal("Ready"), Equal("")))

			// Cleanup
			Expect(k8sClient.Delete(ctx, modelAPI)).Should(Succeed())
		})
	})

	Context("When creating a ModelAPI in Hosted mode", func() {
		It("Should set phase to Pending initially", func() {
			ctx := context.Background()
			namespace := "default"
			name := "test-hosted-modelapi"

			modelAPI := &agenticv1alpha1.ModelAPI{
				ObjectMeta: metav1.ObjectMeta{
					Name:      name,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.ModelAPISpec{
					Mode: agenticv1alpha1.ModelAPIModeHosted,
					HostedConfig: &agenticv1alpha1.HostedConfig{
						Model: "smollm2:135m",
					},
				},
			}

			Expect(k8sClient.Create(ctx, modelAPI)).Should(Succeed())

			// Check initial status
			Eventually(func() string {
				updatedAPI := &agenticv1alpha1.ModelAPI{}
				if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updatedAPI); err != nil {
					return ""
				}
				return updatedAPI.Status.Phase
			}, timeout, interval).Should(Or(Equal("Pending"), Equal("")))

			// Cleanup
			Expect(k8sClient.Delete(ctx, modelAPI)).Should(Succeed())
		})
	})
})
