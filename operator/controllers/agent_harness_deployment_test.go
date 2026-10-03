package controllers

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestConstructDeploymentUsesHarnessImageAndEnv(t *testing.T) {
	t.Setenv("DEFAULT_AGENT_IMAGE", "example/agent:test")

	agent := harnessAgent("pi")
	runtimeConfig := &HarnessRuntimeConfig{Image: "ghcr.io/axsaucedo/kaos-harness-pi:test", Driver: "pi"}

	deployment, err := (&AgentReconciler{}).constructDeployment(agent, &kaosv1alpha1.ModelAPI{}, nil, nil, "", "", "", runtimeConfig)
	if err != nil {
		t.Fatalf("constructDeployment: %v", err)
	}

	container := agentContainer(t, deployment.Spec.Template.Spec)
	if container.Image != runtimeConfig.Image {
		t.Errorf("image = %q, want the harness runtime image", container.Image)
	}
	for name, value := range map[string]string{
		"HARNESS_DRIVER":    "pi",
		"HARNESS_WORKSPACE": "/workspace",
		"HARNESS_STATE_DIR": "/state",
	} {
		got, ok := envByName(container.Env, name)
		if !ok || got.Value != value {
			t.Errorf("%s = %q (found=%v), want %q", name, got.Value, ok, value)
		}
	}
	if len(deployment.Spec.Template.Spec.InitContainers) != 0 {
		t.Errorf("no workspace configured but initContainers were added: %#v", deployment.Spec.Template.Spec.InitContainers)
	}
}

func TestConstructDeploymentWithoutHarnessHasNoHarnessEnv(t *testing.T) {
	t.Setenv("DEFAULT_AGENT_IMAGE", "example/agent:test")

	deployment, err := (&AgentReconciler{}).constructDeployment(newAgent("demo", "researcher"), &kaosv1alpha1.ModelAPI{}, nil, nil, "", "", "", nil)
	if err != nil {
		t.Fatalf("constructDeployment: %v", err)
	}

	container := agentContainer(t, deployment.Spec.Template.Spec)
	if container.Image != "example/agent:test" {
		t.Errorf("image = %q, want the default agent image", container.Image)
	}
	if _, ok := envByName(container.Env, "HARNESS_DRIVER"); ok {
		t.Error("HARNESS_DRIVER must not be set for a plain agent")
	}
}

func TestConstructDeploymentHarnessWorkspaceSurvivesContainerOverride(t *testing.T) {
	t.Setenv("DEFAULT_AGENT_IMAGE", "example/agent:test")

	agent := harnessAgent("pi")
	agent.Spec.Harness.Workspace = &kaosv1alpha1.WorkspaceConfig{RepoURL: "https://github.com/acme/repo", Branch: "dev"}
	// A container override is merged after the operator-generated plumbing, so
	// both the generated mounts and the user's override must be present.
	agent.Spec.Container = &kaosv1alpha1.ContainerOverride{
		WorkingDir: "/workspace",
		Resources: &corev1.ResourceRequirements{
			Limits: corev1.ResourceList{corev1.ResourceMemory: resourceQuantity(t, "2Gi")},
		},
	}

	deployment, err := (&AgentReconciler{}).constructDeployment(agent, &kaosv1alpha1.ModelAPI{}, nil, nil, "", "", "",
		&HarnessRuntimeConfig{Image: "ghcr.io/axsaucedo/kaos-harness-pi:test", Driver: "pi"})
	if err != nil {
		t.Fatalf("constructDeployment: %v", err)
	}

	spec := deployment.Spec.Template.Spec
	if len(spec.InitContainers) != 1 || spec.InitContainers[0].Name != "workspace-clone" {
		t.Fatalf("workspace-clone initContainer missing: %#v", spec.InitContainers)
	}
	if !hasVolume(spec.Volumes, "workspace") || !hasVolume(spec.Volumes, "state") {
		t.Errorf("workspace/state volumes missing: %#v", spec.Volumes)
	}

	container := agentContainer(t, spec)
	if container.WorkingDir != "/workspace" {
		t.Errorf("workingDir = %q, want /workspace", container.WorkingDir)
	}
	if !hasMount(container.VolumeMounts, "workspace", "/workspace") || !hasMount(container.VolumeMounts, "state", "/state") {
		t.Errorf("agent mounts = %#v, want workspace and state", container.VolumeMounts)
	}
}

func resourceQuantity(t *testing.T, value string) resource.Quantity {
	t.Helper()
	q, err := resource.ParseQuantity(value)
	if err != nil {
		t.Fatalf("parse quantity %q: %v", value, err)
	}
	return q
}
