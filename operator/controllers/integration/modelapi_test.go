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
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// uniqueModelAPIName generates unique names to avoid conflicts between tests
func uniqueModelAPIName(base string) string {
	return fmt.Sprintf("%s-%d", base, time.Now().UnixNano()%100000)
}

var _ = Describe("ModelAPI Controller", func() {
	ctx := context.Background()
	const namespace = "default"

	It("should create Deployment, Service and ConfigMap in Proxy mode with models list", func() {
		name := uniqueModelAPIName("proxy-api")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models:  []string{"*"},
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

		// Verify PROXY_API_BASE env var is set
		container := deployment.Spec.Template.Spec.Containers[0]
		var foundProxyAPIBase bool
		for _, env := range container.Env {
			if env.Name == "PROXY_API_BASE" && env.Value == "http://localhost:11434" {
				foundProxyAPIBase = true
				break
			}
		}
		Expect(foundProxyAPIBase).To(BeTrue(), "PROXY_API_BASE env var should be set")

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
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("api_base: \"os.environ/PROXY_API_BASE\""))

		// Verify status endpoint and supportedModels are set
		Eventually(func() bool {
			updated := &kaosv1alpha1.ModelAPI{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated); err != nil {
				return false
			}
			return containsSubstring(updated.Status.Endpoint, fmt.Sprintf("modelapi-%s", name))
		}, timeout, interval).Should(BeTrue())
	})

	It("should create ConfigMap with multiple models", func() {
		name := uniqueModelAPIName("proxy-multi")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
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

		// Verify ConfigMap is created with both models
		configMap := &corev1.ConfigMap{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap)
		}, timeout, interval).Should(Succeed())
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("model_name: \"openai/gpt-4\""))
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("model_name: \"anthropic/claude-3\""))
	})

	It("should inject PROXY_API_KEY from direct value", func() {
		name := uniqueModelAPIName("proxy-apikey")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"openai/*"},
					APIKey: &kaosv1alpha1.ApiKeySource{
						Value: "test-api-key",
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Verify Deployment has PROXY_API_KEY env var
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		container := deployment.Spec.Template.Spec.Containers[0]
		var foundAPIKey bool
		for _, env := range container.Env {
			if env.Name == "PROXY_API_KEY" && env.Value == "test-api-key" {
				foundAPIKey = true
				break
			}
		}
		Expect(foundAPIKey).To(BeTrue(), "PROXY_API_KEY env var should be set")

		// Verify ConfigMap includes api_key reference
		configMap := &corev1.ConfigMap{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap)
		}, timeout, interval).Should(Succeed())
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("api_key: \"os.environ/PROXY_API_KEY\""))
	})

	It("should apply podSpec overrides in Proxy mode", func() {
		name := uniqueModelAPIName("proxy-podspec")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"mock-model"},
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
		name := uniqueModelAPIName("hosted-api")
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
		name := uniqueModelAPIName("hosted-update")
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

	It("should trigger rolling update when models list is changed in Proxy mode", func() {
		name := uniqueModelAPIName("proxy-update")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models:  []string{"*"},
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
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("model_name: \"*\""))

		// Update the models list
		Eventually(func() error {
			current := &kaosv1alpha1.ModelAPI{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, current); err != nil {
				return err
			}
			current.Spec.ProxyConfig.Models = []string{"openai/*", "anthropic/*"}
			return k8sClient.Update(ctx, current)
		}, timeout, interval).Should(Succeed())

		// Verify configmap is updated with new models
		Eventually(func() bool {
			if err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap); err != nil {
				return false
			}
			return containsSubstring(configMap.Data["config.yaml"], "model_name: \"openai/*\"") &&
				containsSubstring(configMap.Data["config.yaml"], "model_name: \"anthropic/*\"")
		}, timeout, interval).Should(BeTrue(), "ConfigMap should be updated with new models")
	})

	It("should delete ModelAPI without errors", func() {
		name := uniqueModelAPIName("delete-api")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
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

		// Wait for deployment to be created
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Delete the ModelAPI
		Expect(k8sClient.Delete(ctx, modelAPI)).To(Succeed())

		// Verify ModelAPI is deleted without errors (finalizer removed successfully)
		Eventually(func() bool {
			err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, &kaosv1alpha1.ModelAPI{})
			return apierrors.IsNotFound(err)
		}, timeout, interval).Should(BeTrue(), "ModelAPI should be deleted")

		// Note: envtest doesn't run garbage collection, so we only verify the CRD deletion
		// In a real cluster, the deployment would be garbage collected via OwnerReferences
	})

	It("should fail when configYaml has models not in models list", func() {
		name := uniqueModelAPIName("configyaml-invalid")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"openai/gpt-4", "anthropic/claude-3"},
					ConfigYaml: &kaosv1alpha1.ConfigYamlSource{
						FromString: `
model_list:
  - model_name: "openai/gpt-4"
    litellm_params:
      model: "openai/gpt-4"
  - model_name: "gemini/gemini-pro"
    litellm_params:
      model: "gemini/gemini-pro"
`,
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Verify ModelAPI status is Failed with validation error
		Eventually(func() string {
			updated := &kaosv1alpha1.ModelAPI{}
			k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated)
			return updated.Status.Phase
		}, timeout, interval).Should(Equal("Failed"))

		// Verify error message mentions the mismatched model
		Eventually(func() bool {
			updated := &kaosv1alpha1.ModelAPI{}
			k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, updated)
			return containsSubstring(updated.Status.Message, "gemini/gemini-pro") &&
				containsSubstring(updated.Status.Message, "not found")
		}, timeout, interval).Should(BeTrue())
	})

	It("should succeed when configYaml models match models list with wildcard", func() {
		name := uniqueModelAPIName("configyaml-valid")
		modelAPI := &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode: kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{
					Models: []string{"openai/*"},
					ConfigYaml: &kaosv1alpha1.ConfigYamlSource{
						FromString: `
model_list:
  - model_name: "openai/gpt-4"
    litellm_params:
      model: "openai/gpt-4"
  - model_name: "openai/gpt-3.5-turbo"
    litellm_params:
      model: "openai/gpt-3.5-turbo"
`,
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, modelAPI)
		}()

		// Verify Deployment is created (validation passed)
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("modelapi-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())

		// Verify ConfigMap uses user-provided configYaml
		configMap := &corev1.ConfigMap{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("litellm-config-%s", name),
				Namespace: namespace,
			}, configMap)
		}, timeout, interval).Should(Succeed())
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("openai/gpt-4"))
		Expect(configMap.Data["config.yaml"]).To(ContainSubstring("openai/gpt-3.5-turbo"))
	})
})

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
