package controllers

import (
	"context"
	"fmt"

	"gopkg.in/yaml.v3"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/types"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

const (
	// harnessRuntimesConfigMapName is the registry of coding-harness runtimes,
	// read live on every reconcile so edits apply without an operator restart.
	harnessRuntimesConfigMapName = "kaos-harness-runtimes"

	harnessWorkspaceInitContainer = "workspace-clone"
	harnessWorkspaceImage         = "alpine/git:2.45.2"
	harnessWorkspaceVolume        = "workspace"
	harnessWorkspacePath          = "/workspace"
	harnessStateVolume            = "state"
	harnessStatePath              = "/state"
	harnessDefaultBranch          = "main"
)

// HarnessRuntimeConfig represents a harness runtime definition from the ConfigMap.
// An empty image means bring-your-own: spec.container.image is then required.
type HarnessRuntimeConfig struct {
	Image       string `yaml:"image"`
	Driver      string `yaml:"driver"`
	Description string `yaml:"description,omitempty"`
}

// HarnessRuntimeRegistry represents the full harness runtime registry from ConfigMap
type HarnessRuntimeRegistry struct {
	Runtimes map[string]HarnessRuntimeConfig `yaml:"runtimes"`
}

// getHarnessRuntimeRegistry fetches and parses the harness runtime registry ConfigMap
func (r *AgentReconciler) getHarnessRuntimeRegistry(ctx context.Context) (*HarnessRuntimeRegistry, error) {
	cm := &corev1.ConfigMap{}
	cmName := types.NamespacedName{
		Name:      harnessRuntimesConfigMapName,
		Namespace: r.SystemNamespace,
	}

	if err := r.Get(ctx, cmName, cm); err != nil {
		return nil, fmt.Errorf("failed to get harness runtime registry ConfigMap: %w", err)
	}

	yamlData, ok := cm.Data["runtimes.yaml"]
	if !ok {
		return nil, fmt.Errorf("runtimes.yaml key not found in ConfigMap")
	}

	var registry HarnessRuntimeRegistry
	if err := yaml.Unmarshal([]byte(yamlData), &registry); err != nil {
		return nil, fmt.Errorf("failed to parse harness runtime registry: %w", err)
	}

	return &registry, nil
}

// resolveHarnessRuntime resolves spec.harness.runtime against the registry and
// applies image precedence: spec.container.image wins over the registry image.
// Returns nil when the agent is not a harness agent.
func (r *AgentReconciler) resolveHarnessRuntime(ctx context.Context, agent *kaosv1alpha1.Agent) (*HarnessRuntimeConfig, error) {
	if agent.Spec.Harness == nil {
		return nil, nil
	}

	registry, err := r.getHarnessRuntimeRegistry(ctx)
	if err != nil {
		return nil, err
	}

	runtimeName := agent.Spec.Harness.Runtime
	runtimeConfig, ok := registry.Runtimes[runtimeName]
	if !ok {
		return nil, fmt.Errorf("unknown harness runtime: %s (not found in registry)", runtimeName)
	}

	overrideImage := ""
	if agent.Spec.Container != nil {
		overrideImage = agent.Spec.Container.Image
	}
	if overrideImage != "" {
		runtimeConfig.Image = overrideImage
	} else if runtimeConfig.Image == "" {
		return nil, fmt.Errorf("harness runtime %s requires a user-supplied spec.container.image", runtimeName)
	}

	return &runtimeConfig, nil
}

// harnessEnvVars are the harness contract env vars injected alongside the
// standard agent env vars.
func harnessEnvVars(runtimeConfig *HarnessRuntimeConfig) []corev1.EnvVar {
	if runtimeConfig == nil {
		return nil
	}
	return []corev1.EnvVar{
		{Name: "HARNESS_DRIVER", Value: runtimeConfig.Driver},
		{Name: "HARNESS_WORKSPACE", Value: harnessWorkspacePath},
		{Name: "HARNESS_STATE_DIR", Value: harnessStatePath},
	}
}

// applyHarnessWorkspace adds the workspace clone initContainer plus the workspace
// and state volumes to the base pod spec. It is applied before the spec.container
// and spec.podSpec merges so users can still override any of it.
func applyHarnessWorkspace(podSpec *corev1.PodSpec, workspace *kaosv1alpha1.WorkspaceConfig) {
	if workspace == nil {
		return
	}

	branch := workspace.Branch
	if branch == "" {
		branch = harnessDefaultBranch
	}

	initContainer := corev1.Container{
		Name:            harnessWorkspaceInitContainer,
		Image:           harnessWorkspaceImage,
		ImagePullPolicy: corev1.PullIfNotPresent,
		Command:         []string{"sh", "-c", workspaceCloneScript(workspace.RepoURL, branch)},
		VolumeMounts: []corev1.VolumeMount{
			{Name: harnessWorkspaceVolume, MountPath: harnessWorkspacePath},
		},
	}
	if workspace.CredentialsSecretRef != nil {
		initContainer.Env = []corev1.EnvVar{{
			Name:      "GIT_TOKEN",
			ValueFrom: &corev1.EnvVarSource{SecretKeyRef: workspace.CredentialsSecretRef},
		}}
	}

	podSpec.InitContainers = append(podSpec.InitContainers, initContainer)
	podSpec.Volumes = append(podSpec.Volumes,
		corev1.Volume{
			Name:         harnessWorkspaceVolume,
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		},
		corev1.Volume{
			Name:         harnessStateVolume,
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		},
	)
	podSpec.Containers[0].VolumeMounts = append(podSpec.Containers[0].VolumeMounts,
		corev1.VolumeMount{Name: harnessWorkspaceVolume, MountPath: harnessWorkspacePath},
		corev1.VolumeMount{Name: harnessStateVolume, MountPath: harnessStatePath},
	)
}

// workspaceCloneScript shallow-clones the branch into /workspace, injecting
// GIT_TOKEN into the clone URL when credentials are supplied.
func workspaceCloneScript(repoURL, branch string) string {
	return fmt.Sprintf(`set -e
REPO_URL=%q
if [ -n "$GIT_TOKEN" ]; then
  REPO_URL=$(echo "$REPO_URL" | sed -e "s#https://#https://x-access-token:$GIT_TOKEN@#")
fi
git clone --depth 1 --single-branch --branch %q "$REPO_URL" %s`, repoURL, branch, harnessWorkspacePath)
}
