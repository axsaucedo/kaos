package controllers

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/utils/ptr"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

// The shorthand container override must be able to express everything a coding
// workload needs (privileges, working directory, extra mounts) without forcing
// users down to the full spec.podSpec escape hatch.
func TestContainerOverrideAppliesSecurityContextWorkingDirAndMounts(t *testing.T) {
	t.Setenv("DEFAULT_AGENT_IMAGE", "example/agent:test")

	agent := newAgent("demo", "coder")
	agent.Spec.Container = &kaosv1alpha1.ContainerOverride{
		SecurityContext: &corev1.SecurityContext{RunAsUser: ptr.To(int64(1000))},
		WorkingDir:      "/workspace",
		VolumeMounts: []corev1.VolumeMount{
			{Name: "extra", MountPath: "/extra"},
		},
	}
	deployment, err := (&AgentReconciler{}).constructDeployment(agent, &kaosv1alpha1.ModelAPI{}, nil, nil, "", "", "", nil)
	if err != nil {
		t.Fatalf("constructDeployment: %v", err)
	}

	container := agentContainer(t, deployment.Spec.Template.Spec)
	if container.SecurityContext == nil || container.SecurityContext.RunAsUser == nil || *container.SecurityContext.RunAsUser != 1000 {
		t.Errorf("securityContext.runAsUser not applied: %#v", container.SecurityContext)
	}
	if container.WorkingDir != "/workspace" {
		t.Errorf("workingDir = %q, want /workspace", container.WorkingDir)
	}
	if !hasMount(container.VolumeMounts, "extra", "/extra") {
		t.Errorf("volumeMounts missing extra:/extra, got %#v", container.VolumeMounts)
	}
}

func TestContainerOverrideLeavesFieldsUnsetWhenEmpty(t *testing.T) {
	t.Setenv("DEFAULT_AGENT_IMAGE", "example/agent:test")

	agent := newAgent("demo", "coder")
	agent.Spec.Container = &kaosv1alpha1.ContainerOverride{Image: "example/custom:1"}

	deployment, err := (&AgentReconciler{}).constructDeployment(agent, &kaosv1alpha1.ModelAPI{}, nil, nil, "", "", "", nil)
	if err != nil {
		t.Fatalf("constructDeployment: %v", err)
	}

	container := agentContainer(t, deployment.Spec.Template.Spec)
	if container.Image != "example/custom:1" {
		t.Errorf("image = %q, want example/custom:1", container.Image)
	}
	if container.SecurityContext != nil || container.WorkingDir != "" {
		t.Errorf("unset overrides leaked into container: %#v / %q", container.SecurityContext, container.WorkingDir)
	}
}

func agentContainer(t *testing.T, spec corev1.PodSpec) corev1.Container {
	t.Helper()
	for _, c := range spec.Containers {
		if c.Name == "agent" {
			return c
		}
	}
	t.Fatalf("agent container not found in pod spec")
	return corev1.Container{}
}

func hasMount(mounts []corev1.VolumeMount, name, path string) bool {
	for _, m := range mounts {
		if m.Name == name && m.MountPath == path {
			return true
		}
	}
	return false
}
