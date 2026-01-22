package integration

import (
	"context"
	"fmt"
	"strings"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// uniqueAgentName generates unique names to avoid conflicts between tests
func uniqueAgentName(base string) string {
	return fmt.Sprintf("%s-%d", base, time.Now().UnixNano()%100000)
}

func boolPtr(b bool) *bool {
	return &b
}

var _ = Describe("Agent Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should create Deployment with correct env vars", func() {
		modelAPIName := uniqueAgentName("agent-modelapi")
		agentName := uniqueAgentName("agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"mock-model"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		maxSteps := int32(10)
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      agentName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description:           "Test agent",
					Instructions:          "You are a test agent.",
					ReasoningLoopMaxSteps: &maxSteps,
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		// Verify Deployment is created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify env vars
		container := deployment.Spec.Template.Spec.Containers[0]
		envMap := make(map[string]string)
		for _, env := range container.Env {
			envMap[env.Name] = env.Value
		}
		Expect(envMap["AGENT_NAME"]).To(Equal(agentName))
		Expect(envMap["AGENT_DESCRIPTION"]).To(Equal("Test agent"))
		Expect(envMap["AGENT_INSTRUCTIONS"]).To(Equal("You are a test agent."))
		Expect(envMap["AGENTIC_LOOP_MAX_STEPS"]).To(Equal("10"))

		// Verify Service is created (expose defaults to true)
		service := &corev1.Service{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, service)
		}, timeout, interval).Should(Succeed())
	})

	It("should apply podSpec overrides to agent deployment", func() {
		modelAPIName := uniqueAgentName("podspec-modelapi")
		agentName := uniqueAgentName("podspec-agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"mock-model"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      agentName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "Test agent with podSpec",
				},
				PodSpec: &corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name: "agent",
							Resources: corev1.ResourceRequirements{
								Requests: corev1.ResourceList{
									corev1.ResourceCPU: resource.MustParse("100m"),
								},
							},
						},
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		// Verify Deployment is created with merged resources
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Resources.Requests.Cpu().String()).To(Equal("100m"))
	})

	It("should set PEER_AGENTS env var when sub-agents exist", func() {
		modelAPIName := uniqueAgentName("multi-modelapi")
		coordinatorName := uniqueAgentName("coordinator")
		workerName := uniqueAgentName("worker")

		// Create ModelAPI
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"mock-model"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Create worker first
		worker := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      workerName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "Worker agent",
				},
			},
		}
		Expect(k8sClient.Create(ctx, worker)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, worker)
		}()

		// Wait for worker to get endpoint
		Eventually(func() string {
			updated := &kaosv1alpha1.Agent{}
			k8sClient.Get(ctx, types.NamespacedName{Name: workerName, Namespace: namespace}, updated)
			return updated.Status.Endpoint
		}, timeout, interval).ShouldNot(BeEmpty())

		// Create coordinator that references worker
		coordinator := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      coordinatorName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "Coordinator agent",
				},
				AgentNetwork: &kaosv1alpha1.AgentNetworkConfig{
					Access: []string{workerName},
				},
			},
		}
		Expect(k8sClient.Create(ctx, coordinator)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, coordinator)
		}()

		// Verify coordinator Deployment has PEER_AGENTS
		deployment := &appsv1.Deployment{}
		Eventually(func() bool {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", coordinatorName),
				Namespace: namespace,
			}, deployment); err != nil {
				return false
			}
			container := deployment.Spec.Template.Spec.Containers[0]
			for _, env := range container.Env {
				if env.Name == "PEER_AGENTS" && env.Value == workerName {
					return true
				}
			}
			return false
		}, timeout, interval).Should(BeTrue(), "PEER_AGENTS should contain worker")
	})

	It("should trigger rolling update when agent config is changed", func() {
		modelAPIName := uniqueAgentName("update-modelapi")
		agentName := uniqueAgentName("update-agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"mock-model"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Wait for ModelAPI to be ready
		Eventually(func() string {
			updated := &kaosv1alpha1.ModelAPI{}
			k8sClient.Get(ctx, types.NamespacedName{Name: modelAPIName, Namespace: namespace}, updated)
			return updated.Status.Endpoint
		}, timeout, interval).ShouldNot(BeEmpty())

		// Create Agent with WaitForDependencies=false to bypass ModelAPI ready check
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      agentName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description:  "Initial description",
					Instructions: "Initial instructions",
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		// Wait for initial deployment
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Store the initial hash
		initialHash := deployment.Spec.Template.Annotations["kaos.tools/pod-spec-hash"]
		Expect(initialHash).NotTo(BeEmpty())

		// Update the agent instructions
		Eventually(func() error {
			current := &kaosv1alpha1.Agent{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, current); err != nil {
				return err
			}
			current.Spec.Config.Instructions = "Updated instructions"
			return k8sClient.Update(ctx, current)
		}, timeout, interval).Should(Succeed())

		// Verify deployment is updated with new hash
		Eventually(func() bool {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, deployment); err != nil {
				return false
			}
			newHash := deployment.Spec.Template.Annotations["kaos.tools/pod-spec-hash"]
			// Hash should change
			return newHash != initialHash && newHash != ""
		}, timeout, interval).Should(BeTrue(), "Deployment hash should change after config update")
	})

	It("should delete Agent without errors", func() {
		modelAPIName := uniqueAgentName("delete-modelapi")
		agentName := uniqueAgentName("delete-agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"mock-model"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      agentName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "Agent to be deleted",
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())

		// Wait for deployment to be created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Delete the Agent
		Expect(k8sClient.Delete(ctx, agent)).To(Succeed())

		// Verify Agent is deleted without errors (finalizer removed successfully)
		Eventually(func() bool {
			err := k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, &kaosv1alpha1.Agent{})
			return apierrors.IsNotFound(err)
		}, timeout, interval).Should(BeTrue(), "Agent should be deleted")

		// Note: envtest doesn't run garbage collection, so we only verify the CRD deletion
		// In a real cluster, the deployment would be garbage collected via OwnerReferences
	})

	It("should fail agent when model is not supported by ModelAPI", func() {
		modelAPIName := uniqueAgentName("unsupported-modelapi")
		agentName := uniqueAgentName("unsupported-agent")

		// Create ModelAPI with specific models (not matching the agent's model)
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"openai/gpt-4", "anthropic/claude-3"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Wait for ModelAPI to have endpoint (reconcile has processed it)
		Eventually(func() bool {
			updated := &kaosv1alpha1.ModelAPI{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: modelAPIName, Namespace: namespace}, updated); err != nil {
				return false
			}
			return updated.Status.Endpoint != ""
		}, timeout, interval).Should(BeTrue())

		// Create Agent with unsupported model
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      agentName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "gemini/gemini-pro", // Not in ModelAPI's supported models
				WaitForDependencies: boolPtr(false),
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		// Verify Agent status is Failed with model validation error
		Eventually(func() string {
			updated := &kaosv1alpha1.Agent{}
			k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated)
			return updated.Status.Phase
		}, timeout, interval).Should(Equal("Failed"))

		// Verify error message mentions the unsupported model
		Eventually(func() bool {
			updated := &kaosv1alpha1.Agent{}
			k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated)
			return strings.Contains(updated.Status.Message, "gemini/gemini-pro") &&
				strings.Contains(updated.Status.Message, "not supported")
		}, timeout, interval).Should(BeTrue())
	})

	It("should allow agent when model matches wildcard pattern", func() {
		modelAPIName := uniqueAgentName("wildcard-modelapi")
		agentName := uniqueAgentName("wildcard-agent")

		// Create ModelAPI with wildcard pattern
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"openai/*"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Wait for ModelAPI to have endpoint (reconcile has processed it)
		Eventually(func() bool {
			updated := &kaosv1alpha1.ModelAPI{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: modelAPIName, Namespace: namespace}, updated); err != nil {
				return false
			}
			return updated.Status.Endpoint != ""
		}, timeout, interval).Should(BeTrue())

		// Create Agent with model matching wildcard
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{
				Name:      agentName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "openai/gpt-4-turbo", // Matches openai/*
				WaitForDependencies: boolPtr(false),
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		// Verify Deployment is created (validation passed)
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", agentName),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify MODEL_NAME env var is set to the agent's model
		container := deployment.Spec.Template.Spec.Containers[0]
		var foundModelName string
		for _, env := range container.Env {
			if env.Name == "MODEL_NAME" {
				foundModelName = env.Value
				break
			}
		}
		Expect(foundModelName).To(Equal("openai/gpt-4-turbo"))
	})
})
