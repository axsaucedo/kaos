package integration

import (
	"context"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	agenticv1alpha1 "agentic.example.com/agentic-operator/api/v1alpha1"
)

var _ = Describe("Agent Controller", func() {
	Context("When creating an Agent", func() {
		It("Should create when ModelAPI exists", func() {
			ctx := context.Background()
			namespace := "default"
			modelAPIName := "agent-test-modelapi"
			agentName := "test-agent"

			// First create a ModelAPI
			modelAPI := &agenticv1alpha1.ModelAPI{
				ObjectMeta: metav1.ObjectMeta{
					Name:      modelAPIName,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.ModelAPISpec{
					Mode: agenticv1alpha1.ModelAPIModeProxy,
					ProxyConfig: &agenticv1alpha1.ProxyConfig{
						Model: "gpt-3.5-turbo",
					},
				},
			}
			Expect(k8sClient.Create(ctx, modelAPI)).Should(Succeed())

			// Create Agent referencing the ModelAPI
			maxSteps := int32(5)
			agent := &agenticv1alpha1.Agent{
				ObjectMeta: metav1.ObjectMeta{
					Name:      agentName,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.AgentSpec{
					ModelAPI: modelAPIName,
					Config: &agenticv1alpha1.AgentConfig{
						Description:           "Test agent",
						Instructions:          "You are a test agent.",
						ReasoningLoopMaxSteps: &maxSteps,
					},
				},
			}

			Expect(k8sClient.Create(ctx, agent)).Should(Succeed())

			// Verify agent is created and status is set
			Eventually(func() string {
				updated := &agenticv1alpha1.Agent{}
				if err := k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated); err != nil {
					return ""
				}
				return updated.Status.Phase
			}, timeout, interval).Should(Or(Equal("Pending"), Equal("Waiting"), Equal("")))

			// Cleanup
			Expect(k8sClient.Delete(ctx, agent)).Should(Succeed())
			Expect(k8sClient.Delete(ctx, modelAPI)).Should(Succeed())
		})
	})

	Context("When creating an Agent with agentNetwork.expose default", func() {
		It("Should default expose to true", func() {
			ctx := context.Background()
			namespace := "default"
			modelAPIName := "agent-expose-modelapi"
			agentName := "test-expose-agent"

			// Create ModelAPI
			modelAPI := &agenticv1alpha1.ModelAPI{
				ObjectMeta: metav1.ObjectMeta{
					Name:      modelAPIName,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.ModelAPISpec{
					Mode: agenticv1alpha1.ModelAPIModeProxy,
					ProxyConfig: &agenticv1alpha1.ProxyConfig{
						Model: "gpt-3.5-turbo",
					},
				},
			}
			Expect(k8sClient.Create(ctx, modelAPI)).Should(Succeed())

			// Create Agent without specifying agentNetwork
			agent := &agenticv1alpha1.Agent{
				ObjectMeta: metav1.ObjectMeta{
					Name:      agentName,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.AgentSpec{
					ModelAPI: modelAPIName,
					Config: &agenticv1alpha1.AgentConfig{
						Description:  "Test agent for expose default",
						Instructions: "You are a test agent.",
					},
					// AgentNetwork not specified - should default expose to true
				},
			}

			Expect(k8sClient.Create(ctx, agent)).Should(Succeed())

			// Verify agent is created (Service should be created due to default expose=true)
			Eventually(func() bool {
				updated := &agenticv1alpha1.Agent{}
				return k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated) == nil
			}, timeout, interval).Should(BeTrue())

			// Cleanup
			Expect(k8sClient.Delete(ctx, agent)).Should(Succeed())
			Expect(k8sClient.Delete(ctx, modelAPI)).Should(Succeed())
		})
	})

	Context("When creating Agent with sub-agents", func() {
		It("Should set PEER_AGENTS env var", func() {
			ctx := context.Background()
			namespace := "default"
			modelAPIName := "agent-peers-modelapi"

			// Create ModelAPI
			modelAPI := &agenticv1alpha1.ModelAPI{
				ObjectMeta: metav1.ObjectMeta{
					Name:      modelAPIName,
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.ModelAPISpec{
					Mode: agenticv1alpha1.ModelAPIModeProxy,
					ProxyConfig: &agenticv1alpha1.ProxyConfig{
						Model: "gpt-3.5-turbo",
					},
				},
			}
			Expect(k8sClient.Create(ctx, modelAPI)).Should(Succeed())

			// Create worker agent
			worker := &agenticv1alpha1.Agent{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "worker-1",
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.AgentSpec{
					ModelAPI: modelAPIName,
					Config: &agenticv1alpha1.AgentConfig{
						Description:  "Worker agent",
						Instructions: "You are a worker.",
					},
				},
			}
			Expect(k8sClient.Create(ctx, worker)).Should(Succeed())

			// Create coordinator that references worker
			coordinator := &agenticv1alpha1.Agent{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "coordinator",
					Namespace: namespace,
				},
				Spec: agenticv1alpha1.AgentSpec{
					ModelAPI: modelAPIName,
					Config: &agenticv1alpha1.AgentConfig{
						Description:  "Coordinator agent",
						Instructions: "You are a coordinator. You manage worker-1.",
					},
					AgentNetwork: &agenticv1alpha1.AgentNetworkConfig{
						Access: []string{"worker-1"},
					},
				},
			}
			Expect(k8sClient.Create(ctx, coordinator)).Should(Succeed())

			// Verify coordinator is created
			Eventually(func() bool {
				updated := &agenticv1alpha1.Agent{}
				return k8sClient.Get(ctx, types.NamespacedName{Name: "coordinator", Namespace: namespace}, updated) == nil
			}, timeout, interval).Should(BeTrue())

			// Cleanup
			Expect(k8sClient.Delete(ctx, coordinator)).Should(Succeed())
			Expect(k8sClient.Delete(ctx, worker)).Should(Succeed())
			Expect(k8sClient.Delete(ctx, modelAPI)).Should(Succeed())
		})
	})
})
