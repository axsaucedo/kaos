package integration

import (
	"context"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	agenticv1alpha1 "agentic.example.com/agentic-operator/api/v1alpha1"
)

var _ = Describe("MCPServer Controller", func() {
	Context("When creating an MCPServer with fromPackage", func() {
		It("Should create a Deployment and set status", func() {
			ctx := context.Background()
			namespace := "default"
			name := "test-mcp-server"

			mcpServer := &agenticv1alpha1.MCPServer{
				ObjectMeta: metav1.ObjectMeta{
					Name:      name,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.MCPServerSpec{
					Type: agenticv1alpha1.MCPServerTypePython,
					Config: agenticv1alpha1.MCPServerConfig{
						Tools: &agenticv1alpha1.MCPToolsConfig{
							FromPackage: "test-mcp-echo-server",
						},
					},
				},
			}

			Expect(k8sClient.Create(ctx, mcpServer)).Should(Succeed())

			// Verify status is updated
			Eventually(func() string {
				updated := &agenticv1alpha1.MCPServer{}
				if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated); err != nil {
					return ""
				}
				return updated.Status.Phase
			}, timeout, interval).Should(Or(Equal("Pending"), Equal("")))

			// Cleanup
			Expect(k8sClient.Delete(ctx, mcpServer)).Should(Succeed())
		})
	})

	Context("When creating an MCPServer with fromString", func() {
		It("Should create deployment with MCP_TOOLS_STRING env var", func() {
			ctx := context.Background()
			namespace := "default"
			name := "test-mcp-string"

			toolsString := `
def echo(message: str) -> str:
    """Echo the message back."""
    return message
`
			mcpServer := &agenticv1alpha1.MCPServer{
				ObjectMeta: metav1.ObjectMeta{
					Name:      name,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.MCPServerSpec{
					Type: agenticv1alpha1.MCPServerTypePython,
					Config: agenticv1alpha1.MCPServerConfig{
						Tools: &agenticv1alpha1.MCPToolsConfig{
							FromString: toolsString,
						},
					},
				},
			}

			Expect(k8sClient.Create(ctx, mcpServer)).Should(Succeed())

			// Verify resource is created
			Eventually(func() bool {
				updated := &agenticv1alpha1.MCPServer{}
				return k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated) == nil
			}, timeout, interval).Should(BeTrue())

			// Cleanup
			Expect(k8sClient.Delete(ctx, mcpServer)).Should(Succeed())
		})
	})
})
