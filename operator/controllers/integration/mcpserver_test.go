package integration

import (
	"context"
	"fmt"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// uniqueMCPServerName generates unique names to avoid conflicts between tests
func uniqueMCPServerName(base string) string {
	return fmt.Sprintf("%s-%d", base, time.Now().UnixNano()%100000)
}

var _ = Describe("MCPServer Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should create Deployment with MCP_TOOLS_STRING env var for fromString tools", func() {
		name := uniqueMCPServerName("mcp-string")
		toolsString := `
def echo(message: str) -> str:
    """Echo the message back."""
    return message
`
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Type: kaosv1alpha1.MCPServerTypePython,
				Config: kaosv1alpha1.MCPServerConfig{
					Tools: &kaosv1alpha1.MCPToolsConfig{
						FromString: toolsString,
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Verify Deployment is created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify MCP_TOOLS_STRING env var is set
		container := deployment.Spec.Template.Spec.Containers[0]
		var foundEnv bool
		for _, env := range container.Env {
			if env.Name == "MCP_TOOLS_STRING" {
				foundEnv = true
				Expect(env.Value).To(ContainSubstring("def echo"))
				break
			}
		}
		Expect(foundEnv).To(BeTrue(), "MCP_TOOLS_STRING env var should be set")

		// Verify Service is created
		service := &corev1.Service{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, service)
		}, timeout, interval).Should(Succeed())

		// Verify status endpoint is set
		Eventually(func() string {
			updated := &kaosv1alpha1.MCPServer{}
			k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated)
			return updated.Status.Endpoint
		}, timeout, interval).Should(ContainSubstring(fmt.Sprintf("mcpserver-%s", name)))
	})

	It("should create Deployment with pip install for fromPackage tools", func() {
		name := uniqueMCPServerName("mcp-package")
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Type: kaosv1alpha1.MCPServerTypePython,
				Config: kaosv1alpha1.MCPServerConfig{
					Tools: &kaosv1alpha1.MCPToolsConfig{
						FromPackage: "mcp-echo-server",
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Verify Deployment is created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify command includes sh -c
		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Command).To(ContainElement("sh"))
		Expect(container.Command).To(ContainElement("-c"))
	})

	It("should trigger rolling update when tools.fromString is changed", func() {
		name := uniqueMCPServerName("mcp-update")
		initialTools := `
def echo(message: str) -> str:
    """Echo the message back."""
    return message
`
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Type: kaosv1alpha1.MCPServerTypePython,
				Config: kaosv1alpha1.MCPServerConfig{
					Tools: &kaosv1alpha1.MCPToolsConfig{
						FromString: initialTools,
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, mcp)
		}()

		// Wait for initial deployment
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Store the initial hash
		initialHash := deployment.Spec.Template.Annotations["kaos.tools/pod-spec-hash"]
		Expect(initialHash).NotTo(BeEmpty())

		// Update the tools
		newTools := `
def greet(name: str) -> str:
    """Greet the user."""
    return f"Hello, {name}!"
`
		Eventually(func() error {
			current := &kaosv1alpha1.MCPServer{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, current); err != nil {
				return err
			}
			current.Spec.Config.Tools.FromString = newTools
			return k8sClient.Update(ctx, current)
		}, timeout, interval).Should(Succeed())

		// Verify deployment is updated with new hash
		Eventually(func() bool {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment); err != nil {
				return false
			}
			newHash := deployment.Spec.Template.Annotations["kaos.tools/pod-spec-hash"]
			// Hash should change
			return newHash != initialHash && newHash != ""
		}, timeout, interval).Should(BeTrue(), "Deployment hash should change after tools update")
	})

	It("should delete MCPServer without errors", func() {
		name := uniqueMCPServerName("mcp-delete")
		toolsString := `
def echo(message: str) -> str:
    """Echo the message back."""
    return message
`
		mcp := &kaosv1alpha1.MCPServer{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.MCPServerSpec{
				Type: kaosv1alpha1.MCPServerTypePython,
				Config: kaosv1alpha1.MCPServerConfig{
					Tools: &kaosv1alpha1.MCPToolsConfig{
						FromString: toolsString,
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, mcp)).To(Succeed())

		// Wait for deployment to be created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("mcpserver-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Delete the MCPServer
		Expect(k8sClient.Delete(ctx, mcp)).To(Succeed())

		// Verify MCPServer is deleted without errors (finalizer removed successfully)
		Eventually(func() bool {
			err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, &kaosv1alpha1.MCPServer{})
			return apierrors.IsNotFound(err)
		}, timeout, interval).Should(BeTrue(), "MCPServer should be deleted")

		// Note: envtest doesn't run garbage collection, so we only verify the CRD deletion
		// In a real cluster, the deployment would be garbage collected via OwnerReferences
	})
})
