package integration

import (
	"context"
	"fmt"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

var _ = Describe("Agent Harness Runtime Registry", func() {
	ctx := context.Background()
	const namespace = "default"

	var modelAPI *kaosv1alpha1.ModelAPI

	BeforeEach(func() {
		modelAPI = &kaosv1alpha1.ModelAPI{
			ObjectMeta: metav1.ObjectMeta{Name: uniqueAgentName("harness-modelapi"), Namespace: namespace},
			Spec: kaosv1alpha1.ModelAPISpec{
				Mode:        kaosv1alpha1.ModelAPIModeProxy,
				ProxyConfig: &kaosv1alpha1.ProxyConfig{Models: []string{"mock-model"}},
			},
		}
		Expect(k8sClient.Create(ctx, modelAPI)).To(Succeed())
	})

	AfterEach(func() {
		k8sClient.Delete(ctx, modelAPI)
	})

	newHarnessAgent := func(name string, harness *kaosv1alpha1.HarnessConfig) *kaosv1alpha1.Agent {
		return &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPI.Name,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Harness:             harness,
			},
		}
	}

	getDeployment := func(name string) *appsv1.Deployment {
		deployment := &appsv1.Deployment{}
		Eventually(func() error {
			return k8sClient.Get(ctx, types.NamespacedName{
				Name:      fmt.Sprintf("agent-%s", name),
				Namespace: namespace,
			}, deployment)
		}, timeout, interval).Should(Succeed())
		return deployment
	}

	It("should resolve the pi harness runtime and inject the harness env contract", func() {
		name := uniqueAgentName("harness-pi")
		agent := newHarnessAgent(name, &kaosv1alpha1.HarnessConfig{Runtime: "pi"})
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		container := getDeployment(name).Spec.Template.Spec.Containers[0]
		Expect(container.Image).To(Equal("ghcr.io/axsaucedo/kaos-harness-pi:test"))
		Expect(container.Env).To(ContainElements(
			corev1.EnvVar{Name: "HARNESS_DRIVER", Value: "pi"},
			corev1.EnvVar{Name: "HARNESS_WORKSPACE", Value: "/workspace"},
			corev1.EnvVar{Name: "HARNESS_STATE_DIR", Value: "/state"},
		))
	})

	It("should prefer spec.container.image over the registry image", func() {
		name := uniqueAgentName("harness-override")
		agent := newHarnessAgent(name, &kaosv1alpha1.HarnessConfig{Runtime: "pi"})
		agent.Spec.Container = &kaosv1alpha1.ContainerOverride{Image: "example/my-pi:9"}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		container := getDeployment(name).Spec.Template.Spec.Containers[0]
		Expect(container.Image).To(Equal("example/my-pi:9"))
	})

	It("should clone the workspace via an initContainer when a workspace is set", func() {
		name := uniqueAgentName("harness-workspace")
		agent := newHarnessAgent(name, &kaosv1alpha1.HarnessConfig{
			Runtime: "pi",
			Workspace: &kaosv1alpha1.WorkspaceConfig{
				RepoURL: "https://github.com/acme/repo",
				Branch:  "dev",
				CredentialsSecretRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "git-creds"},
					Key:                  "token",
				},
			},
		})
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		podSpec := getDeployment(name).Spec.Template.Spec
		Expect(podSpec.InitContainers).To(HaveLen(1))
		initContainer := podSpec.InitContainers[0]
		Expect(initContainer.Name).To(Equal("workspace-clone"))
		Expect(initContainer.Image).To(Equal("alpine/git:2.45.2"))
		Expect(initContainer.Command[2]).To(ContainSubstring(`--branch "dev"`))
		Expect(initContainer.Env[0].Name).To(Equal("GIT_TOKEN"))

		volumeNames := []string{}
		for _, v := range podSpec.Volumes {
			volumeNames = append(volumeNames, v.Name)
		}
		Expect(volumeNames).To(ContainElements("workspace", "state"))

		mountPaths := []string{}
		for _, m := range podSpec.Containers[0].VolumeMounts {
			mountPaths = append(mountPaths, m.MountPath)
		}
		Expect(mountPaths).To(ContainElements("/workspace", "/state"))
	})

	It("should fail for a harness runtime not in the registry", func() {
		name := uniqueAgentName("harness-unknown")
		agent := newHarnessAgent(name, &kaosv1alpha1.HarnessConfig{Runtime: "nonexistent-harness"})
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		Eventually(func() string {
			fetched := &kaosv1alpha1.Agent{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, fetched); err != nil {
				return ""
			}
			return fetched.Status.Phase
		}, timeout, interval).Should(Equal("Failed"))
	})

	It("should fail for a bring-your-own runtime without spec.container.image", func() {
		name := uniqueAgentName("harness-byo")
		agent := newHarnessAgent(name, &kaosv1alpha1.HarnessConfig{Runtime: "claude"})
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() {
			k8sClient.Delete(ctx, agent)
		}()

		Eventually(func() string {
			fetched := &kaosv1alpha1.Agent{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, fetched); err != nil {
				return ""
			}
			return fetched.Status.Message
		}, timeout, interval).Should(ContainSubstring("requires a user-supplied spec.container.image"))
	})
})
