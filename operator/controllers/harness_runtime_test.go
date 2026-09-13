package controllers

import (
	"context"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

const testHarnessRuntimes = `
runtimes:
  pi:
    image: ghcr.io/axsaucedo/kaos-harness-pi:test
    driver: pi
    description: "pi coding harness (MIT)"
  claude:
    image: ""
    driver: claude
    description: "Claude Code (proprietary, bring your own image)"
`

func newHarnessReconciler(t *testing.T, objects ...client.Object) *AgentReconciler {
	t.Helper()
	scheme := newTestScheme(t)
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "kaos-harness-runtimes", Namespace: "kaos"},
		Data:       map[string]string{"runtimes.yaml": testHarnessRuntimes},
	}
	builder := fake.NewClientBuilder().WithScheme(scheme).WithObjects(cm)
	for _, o := range objects {
		builder = builder.WithObjects(o)
	}
	return &AgentReconciler{Client: builder.Build(), Scheme: scheme, SystemNamespace: "kaos"}
}

func harnessAgent(runtime string) *kaosv1alpha1.Agent {
	agent := newAgent("demo", "coder")
	agent.Spec.Harness = &kaosv1alpha1.HarnessConfig{Runtime: runtime}
	return agent
}

func TestResolveHarnessRuntimeNilForNonHarnessAgent(t *testing.T) {
	r := newHarnessReconciler(t)
	got, err := r.resolveHarnessRuntime(context.Background(), newAgent("demo", "researcher"))
	if err != nil {
		t.Fatalf("resolveHarnessRuntime: %v", err)
	}
	if got != nil {
		t.Errorf("expected nil harness runtime for a plain agent, got %#v", got)
	}
}

func TestResolveHarnessRuntimeFromRegistry(t *testing.T) {
	r := newHarnessReconciler(t)
	got, err := r.resolveHarnessRuntime(context.Background(), harnessAgent("pi"))
	if err != nil {
		t.Fatalf("resolveHarnessRuntime: %v", err)
	}
	if got.Image != "ghcr.io/axsaucedo/kaos-harness-pi:test" {
		t.Errorf("image = %q, want the registry image", got.Image)
	}
	if got.Driver != "pi" {
		t.Errorf("driver = %q, want pi", got.Driver)
	}
}

func TestResolveHarnessRuntimeUnknownRuntimeFails(t *testing.T) {
	r := newHarnessReconciler(t)
	_, err := r.resolveHarnessRuntime(context.Background(), harnessAgent("nonexistent"))
	if err == nil || !strings.Contains(err.Error(), "unknown harness runtime") {
		t.Fatalf("err = %v, want an unknown harness runtime error", err)
	}
}

func TestResolveHarnessRuntimeMissingConfigMapFails(t *testing.T) {
	scheme := newTestScheme(t)
	r := &AgentReconciler{Client: fake.NewClientBuilder().WithScheme(scheme).Build(), Scheme: scheme, SystemNamespace: "kaos"}
	if _, err := r.resolveHarnessRuntime(context.Background(), harnessAgent("pi")); err == nil {
		t.Fatal("expected an error when the harness runtime ConfigMap is absent")
	}
}

func TestResolveHarnessRuntimeContainerImageWins(t *testing.T) {
	r := newHarnessReconciler(t)
	agent := harnessAgent("pi")
	agent.Spec.Container = &kaosv1alpha1.ContainerOverride{Image: "example/my-pi:9"}
	got, err := r.resolveHarnessRuntime(context.Background(), agent)
	if err != nil {
		t.Fatalf("resolveHarnessRuntime: %v", err)
	}
	if got.Image != "example/my-pi:9" {
		t.Errorf("image = %q, want the spec.container.image override", got.Image)
	}
}

func TestResolveHarnessRuntimeBYORequiresContainerImage(t *testing.T) {
	r := newHarnessReconciler(t)
	_, err := r.resolveHarnessRuntime(context.Background(), harnessAgent("claude"))
	if err == nil || !strings.Contains(err.Error(), "user-supplied spec.container.image") {
		t.Fatalf("err = %v, want a user-supplied image error", err)
	}

	agent := harnessAgent("claude")
	agent.Spec.Container = &kaosv1alpha1.ContainerOverride{Image: "example/claude-code:1"}
	got, err := r.resolveHarnessRuntime(context.Background(), agent)
	if err != nil {
		t.Fatalf("resolveHarnessRuntime with user image: %v", err)
	}
	if got.Image != "example/claude-code:1" || got.Driver != "claude" {
		t.Errorf("resolved = %#v, want the user image with the claude driver", got)
	}
}

func TestHarnessEnvVars(t *testing.T) {
	if harnessEnvVars(nil) != nil {
		t.Error("expected no harness env vars for a plain agent")
	}
	env := harnessEnvVars(&HarnessRuntimeConfig{Driver: "pi"})
	want := map[string]string{
		"HARNESS_DRIVER":    "pi",
		"HARNESS_WORKSPACE": "/workspace",
		"HARNESS_STATE_DIR": "/state",
	}
	for name, value := range want {
		got, ok := envByName(env, name)
		if !ok || got.Value != value {
			t.Errorf("%s = %q (found=%v), want %q", name, got.Value, ok, value)
		}
	}
}

func TestApplyHarnessWorkspaceNoopWithoutWorkspace(t *testing.T) {
	spec := corev1.PodSpec{Containers: []corev1.Container{{Name: "agent"}}}
	applyHarnessWorkspace(&spec, nil)
	if len(spec.InitContainers) != 0 || len(spec.Volumes) != 0 {
		t.Errorf("workspace plumbing added without a workspace: %#v", spec)
	}
}

func TestApplyHarnessWorkspaceAddsInitContainerAndVolumes(t *testing.T) {
	spec := corev1.PodSpec{Containers: []corev1.Container{{Name: "agent"}}}
	applyHarnessWorkspace(&spec, &kaosv1alpha1.WorkspaceConfig{RepoURL: "https://github.com/acme/repo"})

	if len(spec.InitContainers) != 1 {
		t.Fatalf("initContainers = %d, want 1", len(spec.InitContainers))
	}
	init := spec.InitContainers[0]
	if init.Name != "workspace-clone" || init.Image != "alpine/git:2.45.2" {
		t.Errorf("initContainer = %s/%s, want workspace-clone/alpine/git:2.45.2", init.Name, init.Image)
	}
	script := strings.Join(init.Command, " ")
	if !strings.Contains(script, "--depth 1") || !strings.Contains(script, `--branch "main"`) {
		t.Errorf("clone script is not a shallow clone of the default branch: %s", script)
	}
	if !strings.Contains(script, "https://github.com/acme/repo") {
		t.Errorf("clone script missing repo URL: %s", script)
	}
	if len(init.Env) != 0 {
		t.Errorf("no credentials configured but GIT_TOKEN was set: %#v", init.Env)
	}
	if !hasMount(init.VolumeMounts, "workspace", "/workspace") {
		t.Errorf("initContainer missing workspace mount: %#v", init.VolumeMounts)
	}

	if !hasVolume(spec.Volumes, "workspace") || !hasVolume(spec.Volumes, "state") {
		t.Errorf("workspace/state emptyDir volumes missing: %#v", spec.Volumes)
	}
	agentMounts := spec.Containers[0].VolumeMounts
	if !hasMount(agentMounts, "workspace", "/workspace") || !hasMount(agentMounts, "state", "/state") {
		t.Errorf("agent container mounts = %#v, want workspace and state", agentMounts)
	}
}

func TestApplyHarnessWorkspaceBranchAndCredentials(t *testing.T) {
	spec := corev1.PodSpec{Containers: []corev1.Container{{Name: "agent"}}}
	applyHarnessWorkspace(&spec, &kaosv1alpha1.WorkspaceConfig{
		RepoURL: "https://github.com/acme/repo",
		Branch:  "feature/x",
		CredentialsSecretRef: &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: "git-creds"},
			Key:                  "token",
		},
	})

	init := spec.InitContainers[0]
	script := strings.Join(init.Command, " ")
	if !strings.Contains(script, `--branch "feature/x"`) {
		t.Errorf("clone script does not use the requested branch: %s", script)
	}
	if !strings.Contains(script, "$GIT_TOKEN") {
		t.Errorf("clone script does not use GIT_TOKEN: %s", script)
	}
	token, ok := envByName(init.Env, "GIT_TOKEN")
	if !ok || token.ValueFrom == nil || token.ValueFrom.SecretKeyRef == nil {
		t.Fatalf("GIT_TOKEN is not sourced from the credentials secret: %#v", init.Env)
	}
	if token.ValueFrom.SecretKeyRef.Name != "git-creds" || token.ValueFrom.SecretKeyRef.Key != "token" {
		t.Errorf("GIT_TOKEN ref = %#v, want git-creds/token", token.ValueFrom.SecretKeyRef)
	}
}

func hasVolume(volumes []corev1.Volume, name string) bool {
	for _, v := range volumes {
		if v.Name == name {
			return v.EmptyDir != nil
		}
	}
	return false
}
