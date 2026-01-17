package integration

import (
	"context"
	"fmt"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// uniqueName generates unique names to avoid conflicts between tests
func uniqueName(base string) string {
	return fmt.Sprintf("%s-%d", base, time.Now().UnixNano()%100000)
}

var _ = Describe("ModelAPI Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should create Deployment, Service and ConfigMap in Proxy mode", func() {
		name := uniqueName("proxy-api")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					APIBase: "http://localhost:11434",
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Verify Deployment is created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify container uses litellm image
		Expect(deployment.Spec.Template.Spec.Containers).To(HaveLen(1))
		Expect(deployment.Spec.Template.Spec.Containers[0].Image).To(Equal("ghcr.io/berriai/litellm:main-latest"))

		// Verify Service is created
		service := &corev1.Service{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, service)
		}, timeout, interval).Should(Succeed())
		Expect(service.Spec.Ports[0].Port).To(Equal(int32(8000)))

		// Verify ConfigMap is created with wildcard config
		configMap := &corev1.ConfigMap{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap)
		}, timeout, interval).Should(Succeed())
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("model_name: \"*\""))

		// Verify status endpoint is set
		Eventually(func() string {
			updated := &kaosv1alpha1.ModelAPI{}
			k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated)
			return updated.Status.Endpoint
		}, timeout, interval).Should(ContainSubstring(fmt.Sprintf("modelapi-%s", name)))
	})

	It("should apply podSpec overrides in Proxy mode", func() {
		name := uniqueName("proxy-podspec")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Model: "mock-model",
				},
				PodSpec: &corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name: "model-api",
							Resources: corev1.ResourceRequirements{
								Limits: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse("512Mi"),
								},
							},
						},
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Verify Deployment is created with merged podSpec
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify replicas default is 1
		Expect(*deployment.Spec.Replicas).To(Equal(int32(1)))

		// Verify resource limits were merged
		container := deployment.Spec.Template.Spec.Containers[0]
		Expect(container.Resources.Limits.Memory().String()).To(Equal("512Mi"))
	})

	It("should create Deployment with Ollama and init container in Hosted mode", func() {
		name := uniqueName("hosted-api")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeHosted,
				HostedConfig: &kaosv1alpha1.HostedConfig{
					Model: "smollm2:135m",
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Verify Deployment is created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify init container for model pull
		Expect(deployment.Spec.Template.Spec.InitContainers).To(HaveLen(1))
		initContainer := deployment.Spec.Template.Spec.InitContainers[0]
		Expect(initContainer.Name).To(Equal("pull-model"))
		Expect(initContainer.Args[0]).To(ContainSubstring("smollm2:135m"))

		// Verify main container uses ollama
		Expect(deployment.Spec.Template.Spec.Containers[0].Image).To(Equal("alpine/ollama:latest"))

		// Verify Service uses port 11434
		service := &corev1.Service{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, service)
		}, timeout, interval).Should(Succeed())
		Expect(service.Spec.Ports[0].Port).To(Equal(int32(11434)))
	})

	It("should trigger rolling update when model is changed in Hosted mode", func() {
		name := uniqueName("hosted-update")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeHosted,
				HostedConfig: &kaosv1alpha1.HostedConfig{
					Model: "smollm2:135m",
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Wait for initial deployment
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Store the initial pod spec hash
		initialHash := deployment.Spec.Template.Annotations["kaos.tools/pod-spec-hash"]
		Expect(initialHash).NotTo(BeEmpty())
		initialArgs := deployment.Spec.Template.Spec.InitContainers[0].Args[0]
		Expect(initialArgs).To(ContainSubstring("smollm2:135m"))

		// Update the model
		Eventually(func() error {
			current := &kaosv1alpha1.ModelAPI{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, current); err != nil {
				return err
			}
			current.Spec.HostedConfig.Model = "llama2:7b"
			return k8sClient.Update(ctx, current)
		}, timeout, interval).Should(Succeed())

		// Verify deployment is updated with new model and new hash
		Eventually(func() bool {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment); err != nil {
				return false
			}
			newHash := deployment.Spec.Template.Annotations["kaos.tools/pod-spec-hash"]
			newArgs := deployment.Spec.Template.Spec.InitContainers[0].Args[0]
			// Hash should change and new model should be in args
			return newHash != initialHash && newHash != "" && 
				!containsSubstring(newArgs, "smollm2:135m") && 
				containsSubstring(newArgs, "llama2:7b")
		}, timeout, interval).Should(BeTrue(), "Deployment should be updated with new model")
	})

	It("should trigger rolling update when apiBase is changed in Proxy mode", func() {
		name := uniqueName("proxy-update")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					APIBase: "http://localhost:11434",
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Wait for initial deployment and configmap
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		configMap := &corev1.ConfigMap{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap)
		}, timeout, interval).Should(Succeed())
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("http://localhost:11434"))

		// Update the apiBase
		Eventually(func() error {
			current := &kaosv1alpha1.ModelAPI{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, current); err != nil {
				return err
			}
			current.Spec.ProxyConfig.APIBase = "http://newhost:11434"
			return k8sClient.Update(ctx, current)
		}, timeout, interval).Should(Succeed())

		// Verify configmap is updated with new apiBase
		Eventually(func() bool {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap); err != nil {
				return false
			}
			return containsSubstring(configMap.Data["config.yaml"], "http://newhost:11434")
		}, timeout, interval).Should(BeTrue(), "ConfigMap should be updated with new apiBase")
	})
})

var _ = Describe("MCPServer Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should create Deployment with MCP_TOOLS_STRING env var for fromString tools", func() {
		name := uniqueName("mcp-string")
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
		name := uniqueName("mcp-package")
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
		name := uniqueName("mcp-update")
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
})

var _ = Describe("Agent Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should create Deployment with correct env vars", func() {
		modelAPIName := uniqueName("agent-modelapi")
		agentName := uniqueName("agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Model: "mock-model",
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
		Expect(envMap["AGENT_DEBUG_MEMORY_ENDPOINTS"]).To(Equal("true"))

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
		modelAPIName := uniqueName("podspec-modelapi")
		agentName := uniqueName("podspec-agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Model: "mock-model",
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
		modelAPIName := uniqueName("multi-modelapi")
		coordinatorName := uniqueName("coordinator")
		workerName := uniqueName("worker")

		// Create ModelAPI
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Model: "mock-model",
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
		modelAPIName := uniqueName("update-modelapi")
		agentName := uniqueName("update-agent")

		// Create ModelAPI first
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      modelAPIName,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Model: "mock-model",
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
})

func boolPtr(b bool) *bool {
	return &b
}

// containsSubstring checks if s contains substr (helper for test assertions)
func containsSubstring(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) == 0 || 
		(len(s) > 0 && len(substr) > 0 && findSubstring(s, substr)))
}

func findSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
