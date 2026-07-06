package integration

import (
	"context"
	"fmt"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// createReadyMemoryStore provisions a local-mode MemoryStore backed by a Ready
// ModelAPI and drives it to Ready by marking its Deployment available.
func createReadyMemoryStore(ctx context.Context, namespace, name, modelAPIName string) *kaosv1alpha1.MemoryStore {
	store := &kaosv1alpha1.MemoryStore{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: kaosv1alpha1.MemoryStoreSpec{
			Engine: "mem0",
			Storage: kaosv1alpha1.MemoryStorage{
				Type:  kaosv1alpha1.MemoryStorageLocal,
				Local: &kaosv1alpha1.LocalMemoryStorage{Provider: "chroma"},
			},
			Models: kaosv1alpha1.MemoryModels{
				Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
				Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
			},
		},
	}
	Expect(k8sClient.Create(ctx, store)).To(Succeed())

	deployment := &appsv1.Deployment{}
	Eventually(func() error {
		return k8sClient.Get(ctx, types.NamespacedName{
			Name: fmt.Sprintf("memorystore-%s", name), Namespace: namespace}, deployment)
	}, timeout, interval).Should(Succeed())

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
		return updated.Status.Ready
	}, timeout, interval).Should(BeTrue())

	return store
}

func agentMemoryEnv(ctx context.Context, namespace, agentName string) map[string]string {
	deployment := &appsv1.Deployment{}
	Eventually(func() error {
		return k8sClient.Get(ctx, types.NamespacedName{
			Name: fmt.Sprintf("agent-%s", agentName), Namespace: namespace}, deployment)
	}, timeout, interval).Should(Succeed())

	envMap := map[string]string{}
	for _, e := range deployment.Spec.Template.Spec.Containers[0].Env {
		envMap[e.Name] = e.Value
	}
	return envMap
}

var _ = Describe("Agent memory binding", func() {
	ctx := context.Background()
	const namespace = "default"

	It("wires the remote backend, endpoint, scope, and identity when a store is bound and ready", func() {
		modelAPIName := uniqueAgentName("agent-mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		storeName := uniqueAgentName("agent-store")
		store := createReadyMemoryStore(ctx, namespace, storeName, modelAPIName)
		defer func() { k8sClient.Delete(ctx, store) }()

		agentName := uniqueAgentName("agent")
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{Name: agentName, Namespace: namespace},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "mem agent",
					Memory: &kaosv1alpha1.MemoryConfig{
						Type:        "remote",
						MemoryStore: storeName,
						Scope:       "user",
						Tools:       "all",
						FailureMode: "strict",
						ClientParams: &kaosv1alpha1.MemoryClientParams{
							TokenBudget:    int32Ptr(4096),
							RollingSummary: boolPtr(false),
						},
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, agent) }()

		env := agentMemoryEnv(ctx, namespace, agentName)
		Expect(env["MEMORY_ENABLED"]).To(Equal("true"))
		Expect(env["MEMORY_TYPE"]).To(Equal("remote"))
		Expect(env["MEMORY_STORE_ENDPOINT"]).To(Equal(fmt.Sprintf("http://memorystore-%s.%s.svc.cluster.local:8080", storeName, namespace)))
		Expect(env["MEMORY_SCOPE"]).To(Equal("user"))
		Expect(env["MEMORY_TOOLS"]).To(Equal("all"))
		Expect(env["MEMORY_FAILURE_MODE"]).To(Equal("strict"))
		Expect(env["MEMORY_SHORT_TERM_TOKEN_BUDGET"]).To(Equal("4096"))
		Expect(env["MEMORY_ROLLING_SUMMARY"]).To(Equal("false"))
		Expect(env["AGENT_IDENTITY"]).To(Equal(fmt.Sprintf("kaos://agent/%s/%s", namespace, agentName)))

		// Status links the store and reports memory as not degraded.
		Eventually(func() bool {
			updated := &kaosv1alpha1.Agent{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated); err != nil {
				return false
			}
			if updated.Status.LinkedResources["memorystore"] != storeName {
				return false
			}
			for _, c := range updated.Status.Conditions {
				if c.Type == "MemoryDegraded" {
					return c.Status == metav1.ConditionFalse
				}
			}
			return false
		}, timeout, interval).Should(BeTrue())
	})

	It("uses the local backend with no endpoint when memory is enabled without a store", func() {
		modelAPIName := uniqueAgentName("agent-mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		agentName := uniqueAgentName("agent")
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{Name: agentName, Namespace: namespace},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "local mem agent",
					Memory:      &kaosv1alpha1.MemoryConfig{Enabled: boolPtr(true)},
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, agent) }()

		env := agentMemoryEnv(ctx, namespace, agentName)
		Expect(env["MEMORY_TYPE"]).To(Equal("local"))
		Expect(env).NotTo(HaveKey("MEMORY_STORE_ENDPOINT"))
		Expect(env["AGENT_IDENTITY"]).To(Equal(fmt.Sprintf("kaos://agent/%s/%s", namespace, agentName)))
	})

	It("stays Ready with a MemoryDegraded condition when the bound store is missing", func() {
		modelAPIName := uniqueAgentName("agent-mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		agentName := uniqueAgentName("agent")
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{Name: agentName, Namespace: namespace},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "degraded mem agent",
					Memory: &kaosv1alpha1.MemoryConfig{
						Type:        "remote",
						MemoryStore: "does-not-exist",
					},
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, agent) }()

		// No endpoint is injected while the store is unresolved.
		env := agentMemoryEnv(ctx, namespace, agentName)
		Expect(env["MEMORY_TYPE"]).To(Equal("remote"))
		Expect(env).NotTo(HaveKey("MEMORY_STORE_ENDPOINT"))

		// The Deployment is created (agent still serves) and the condition is set.
		Eventually(func() bool {
			updated := &kaosv1alpha1.Agent{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated); err != nil {
				return false
			}
			for _, c := range updated.Status.Conditions {
				if c.Type == "MemoryDegraded" {
					return c.Status == metav1.ConditionTrue
				}
			}
			return false
		}, timeout, interval).Should(BeTrue())
	})

	It("withholds the endpoint and reports degraded while the bound store is not yet ready", func() {
		modelAPIName := uniqueAgentName("agent-mem-model")
		modelAPI := createReadyModelAPI(ctx, namespace, modelAPIName)
		defer func() { k8sClient.Delete(ctx, modelAPI) }()

		// A store whose Deployment never becomes available stays not-ready.
		storeName := uniqueAgentName("agent-store")
		store := &kaosv1alpha1.MemoryStore{
			ObjectMeta: metav1.ObjectMeta{Name: storeName, Namespace: namespace},
			Spec: kaosv1alpha1.MemoryStoreSpec{
				Engine: "mem0",
				Storage: kaosv1alpha1.MemoryStorage{
					Type:  kaosv1alpha1.MemoryStorageLocal,
					Local: &kaosv1alpha1.LocalMemoryStorage{Provider: "chroma"},
				},
				Models: kaosv1alpha1.MemoryModels{
					Summarization: kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-model"},
					Embedding:     kaosv1alpha1.MemoryModelRef{ModelAPI: modelAPIName, Model: "mock-embed"},
				},
			},
		}
		Expect(k8sClient.Create(ctx, store)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, store) }()

		agentName := uniqueAgentName("agent")
		agent := &kaosv1alpha1.Agent{
			ObjectMeta: metav1.ObjectMeta{Name: agentName, Namespace: namespace},
			Spec: kaosv1alpha1.AgentSpec{
				ModelAPI:            modelAPIName,
				Model:               "mock-model",
				WaitForDependencies: boolPtr(false),
				Config: &kaosv1alpha1.AgentConfig{
					Description: "warming mem agent",
					Memory:      &kaosv1alpha1.MemoryConfig{Type: "remote", MemoryStore: storeName},
				},
			},
		}
		Expect(k8sClient.Create(ctx, agent)).To(Succeed())
		defer func() { k8sClient.Delete(ctx, agent) }()

		// State 4: store present but not Ready -> no endpoint, degraded True.
		env := agentMemoryEnv(ctx, namespace, agentName)
		Expect(env["MEMORY_TYPE"]).To(Equal("remote"))
		Expect(env).NotTo(HaveKey("MEMORY_STORE_ENDPOINT"))

		Eventually(func() bool {
			updated := &kaosv1alpha1.Agent{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: agentName, Namespace: namespace}, updated); err != nil {
				return false
			}
			for _, c := range updated.Status.Conditions {
				if c.Type == "MemoryDegraded" {
					return c.Status == metav1.ConditionTrue
				}
			}
			return false
		}, timeout, interval).Should(BeTrue())
	})

	It("rejects invalid memory field combinations via CEL validation", func() {
		modelAPIName := uniqueAgentName("agent-mem-model")

		makeAgent := func(mem *kaosv1alpha1.MemoryConfig) *kaosv1alpha1.Agent {
			return &kaosv1alpha1.Agent{
				ObjectMeta: metav1.ObjectMeta{Name: uniqueAgentName("agent"), Namespace: namespace},
				Spec: kaosv1alpha1.AgentSpec{
					ModelAPI:            modelAPIName,
					Model:               "mock-model",
					WaitForDependencies: boolPtr(false),
					Config:              &kaosv1alpha1.AgentConfig{Memory: mem},
				},
			}
		}

		By("rejecting type local with a memoryStore")
		Expect(k8sClient.Create(ctx, makeAgent(&kaosv1alpha1.MemoryConfig{Type: "local", MemoryStore: "s"}))).NotTo(Succeed())

		By("rejecting type remote without a memoryStore")
		Expect(k8sClient.Create(ctx, makeAgent(&kaosv1alpha1.MemoryConfig{Type: "remote"}))).NotTo(Succeed())

		By("rejecting user scope without a memoryStore")
		Expect(k8sClient.Create(ctx, makeAgent(&kaosv1alpha1.MemoryConfig{Scope: "user"}))).NotTo(Succeed())

		By("rejecting tools without a memoryStore")
		Expect(k8sClient.Create(ctx, makeAgent(&kaosv1alpha1.MemoryConfig{Tools: "all"}))).NotTo(Succeed())
	})
})
