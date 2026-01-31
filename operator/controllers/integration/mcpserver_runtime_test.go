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

// uniqueRuntimeTestName generates unique names for runtime tests
func uniqueRuntimeTestName(base string) string {
	return fmt.Sprintf("%s-%d", base, time.Now().UnixNano()%100000)
}

var _ = Describe("MCPServer Runtime Registry", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should resolve kubernetes runtime from ConfigMap registry", func() {
		name := uniqueRuntimeTestName("mcp-k8s-runtime")
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Runtime: "kubernetes",
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Verify Deployment is created with kubernetes runtime image
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify image from registry
		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Image).To(Equal("ghcr.io/manusa/kubernetes-mcp-server:latest"))
		Expect(container.Args).To(ContainElements("--port", "8000"))
	})

	It("should resolve slack runtime from ConfigMap registry", func() {
		name := uniqueRuntimeTestName("mcp-slack-runtime")
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Runtime: "slack",
				Container: &kaosv1alpha1.ContainerOverride{
					Env: []corev1.EnvVar{
						{Name: "SLACK_BOT_TOKEN", Value: "test-token"},
						{Name: "SLACK_TEAM_ID", Value: "T12345"},
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Verify Deployment is created with slack runtime image
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify image from registry
		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Image).To(Equal("zencoderai/slack-mcp:latest"))
	})

	It("should allow container override even for registered runtimes", func() {
		name := uniqueRuntimeTestName("mcp-override-runtime")
		customImage := "my-custom-rawpython:v1.0.0"
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Runtime: "rawpython",
				Params:  "def test(): pass",
				Container: &kaosv1alpha1.ContainerOverride{
					Image: customImage,
				},
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Verify Deployment uses overridden image
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Image).To(Equal(customImage))
	})

	It("should fail for unknown runtime not in registry", func() {
		name := uniqueRuntimeTestName("mcp-unknown-runtime")
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Runtime: "nonexistent-runtime",
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Verify MCPServer status indicates failure
		Eventually(func() string {
			mcpServer := &kaosv1alpha1.MCPServer{}
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      name,
				Namespace: namespace,
			}, mcpServer); err != nil {
				return ""
			}
			return mcpServer.Status.Phase
		}, timeout, interval).Should(Equal("Failed"))
	})
})
