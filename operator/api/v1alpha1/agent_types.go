package v1alpha1

import (
	"strings"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// +kubebuilder:object:generate=true

// ContainerOverride provides shorthand container configuration.
// Applied as strategic merge patch to the generated container.
type ContainerOverride struct {
	// Image overrides the container image
	// +kubebuilder:validation:Optional
	Image string `json:"image,omitempty"`

	// Command overrides the container entrypoint
	// +kubebuilder:validation:Optional
	Command []string `json:"command,omitempty"`

	// Args overrides the container arguments
	// +kubebuilder:validation:Optional
	Args []string `json:"args,omitempty"`

	// Resources overrides compute resources
	// +kubebuilder:validation:Optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`

	// Env sets environment variables
	// +kubebuilder:validation:Optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentNetworkConfig defines A2A communication settings
type AgentNetworkConfig struct {
	// Expose indicates if this agent exposes an Agent Card endpoint for A2A
	// +kubebuilder:default=true
	Expose *bool `json:"expose,omitempty"`

	// Access is the allowlist of peer agent names this agent can call
	// +kubebuilder:validation:Optional
	Access []string `json:"access,omitempty"`
}

// +kubebuilder:object:generate=true

// +kubebuilder:object:generate=true

// MemoryClientParams carries the per-agent runtime knobs forwarded to the memory
// client. It is deliberately minimal: shared-window, digest, sweeper, and
// extraction knobs are service-global and live on the MemoryStore, because the
// working window is keyed by scope and shared across agents.
type MemoryClientParams struct {
	// TokenBudget caps the verbatim short-term window the runtime replays, in
	// tokens. When unset the runtime uses its built-in default.
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Optional
	TokenBudget *int32 `json:"tokenBudget,omitempty"`

	// RollingSummary controls whether the runtime maintains a rolling summary of
	// evicted turns (default: true in the runtime).
	// +kubebuilder:validation:Optional
	RollingSummary *bool `json:"rollingSummary,omitempty"`
}

// +kubebuilder:object:generate=true

// MemoryConfig defines the agent's memory behaviour. It binds the agent to a
// MemoryStore for the long-term tier and configures the runtime memory client.
// +kubebuilder:validation:XValidation:rule="!has(self.type) || self.type != 'remote' || has(self.memoryStore)",message="type 'remote' requires memoryStore to be set"
// +kubebuilder:validation:XValidation:rule="!has(self.type) || self.type != 'local' || !has(self.memoryStore)",message="type 'local' must not set memoryStore"
// +kubebuilder:validation:XValidation:rule="!has(self.scope) || (self.scope != 'user' && self.scope != 'group') || has(self.memoryStore)",message="scope 'user' or 'group' requires memoryStore to be set"
// +kubebuilder:validation:XValidation:rule="!has(self.tools) || has(self.memoryStore)",message="tools requires memoryStore to be set"
// +kubebuilder:validation:XValidation:rule="!has(self.defaultReadScope) || !has(self.readScopes) || self.defaultReadScope in self.readScopes",message="defaultReadScope must be included in readScopes"
// +kubebuilder:validation:XValidation:rule="!has(self.defaultReadScope) || self.defaultReadScope == 'session' || has(self.memoryStore)",message="non-session defaultReadScope requires memoryStore to be set"
// +kubebuilder:validation:XValidation:rule="!has(self.readScopes) || self.readScopes.all(scope, scope == 'session') || has(self.memoryStore)",message="non-session readScopes require memoryStore to be set"
// +kubebuilder:validation:XValidation:rule="!has(self.readScopes) || size(self.readScopes) <= 1 || (has(self.tools) && (self.tools == 'read' || self.tools == 'all'))",message="multiple readScopes require tools to be 'read' or 'all'"
type MemoryConfig struct {
	// Enabled controls whether memory is enabled (default: true).
	// When disabled the runtime uses a no-op memory implementation.
	// +kubebuilder:default=true
	Enabled *bool `json:"enabled,omitempty"`

	// Type selects the memory backend. "remote" requires a bound memoryStore and
	// uses the central memory service; "local" forbids a memoryStore and uses the
	// pod-local short-term fallback. When omitted it is derived from memoryStore
	// presence (remote if bound, local otherwise).
	// +kubebuilder:validation:Enum=local;remote
	// +kubebuilder:validation:Optional
	Type string `json:"type,omitempty"`

	// MemoryStore is the name of a MemoryStore in the same namespace providing the
	// long-term tier for this agent.
	// +kubebuilder:validation:Optional
	MemoryStore string `json:"memoryStore,omitempty"`

	// Scope selects whose memory this agent reads and writes. "user" and "group"
	// require a bound memoryStore.
	// +kubebuilder:validation:Enum=agent;user;group;session
	// +kubebuilder:default=agent
	// +kubebuilder:validation:Optional
	Scope string `json:"scope,omitempty"`

	// DefaultReadScope selects the single scope used by automatic recall. When
	// omitted it resolves to the effective home Scope.
	// +kubebuilder:validation:Enum=agent;user;group;session
	// +kubebuilder:validation:Optional
	DefaultReadScope string `json:"defaultReadScope,omitempty"`

	// ReadScopes lists the scope levels available to the explicit search_memory
	// tool. When omitted it resolves to only DefaultReadScope.
	// +kubebuilder:validation:items:Enum=agent;user;group;session
	// +kubebuilder:validation:Optional
	ReadScopes []string `json:"readScopes,omitempty"`

	// ClientParams carries the minimal per-agent runtime memory knobs.
	// +kubebuilder:validation:Optional
	ClientParams *MemoryClientParams `json:"clientParams,omitempty"`

	// Tools exposes explicit memory tools to the agent on top of the automatic
	// recall/write baseline: "all" (save + search), "read" (search), "write"
	// (save). Requires a bound memoryStore.
	// +kubebuilder:validation:Enum=all;read;write
	// +kubebuilder:validation:Optional
	Tools string `json:"tools,omitempty"`

	// FailureMode overrides the memory store's default write/forget failure mode
	// for this agent. When unset the store's default_failure_mode governs.
	// +kubebuilder:validation:Enum=soft;strict
	// +kubebuilder:validation:Optional
	FailureMode string `json:"failureMode,omitempty"`
}

// +kubebuilder:object:generate=true

// TelemetryConfig defines OpenTelemetry instrumentation settings.
// Advanced OTel settings can be configured via spec.config.env using standard
// OTEL_* environment variables (e.g., OTEL_EXPORTER_OTLP_INSECURE, OTEL_TRACES_SAMPLER).
type TelemetryConfig struct {
	// Enabled controls whether OpenTelemetry is enabled (default: false)
	// When enabled, traces, metrics, and log correlation are all active.
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// Endpoint is the OTLP gRPC endpoint URL (required when enabled).
	// Example: "http://otel-collector.observability:4317"
	// +kubebuilder:validation:Optional
	Endpoint string `json:"endpoint,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentConfig defines agent-specific configuration
type AgentConfig struct {
	// Description is a human-readable description of the agent
	// +kubebuilder:validation:Optional
	Description string `json:"description,omitempty"`

	// Instructions are the system instructions for the agent. Instructions are
	// re-evaluated on every run and are not retained in the conversation history.
	// +kubebuilder:validation:Optional
	Instructions string `json:"instructions,omitempty"`

	// SystemPrompt is an optional system prompt for the agent. Unlike
	// instructions, a system prompt is retained in the conversation history.
	// When empty, only instructions are applied.
	// +kubebuilder:validation:Optional
	SystemPrompt string `json:"systemPrompt,omitempty"`

	// ReasoningLoopMaxSteps is the maximum number of reasoning steps before stopping
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=20
	// +kubebuilder:default=5
	ReasoningLoopMaxSteps *int32 `json:"reasoningLoopMaxSteps,omitempty"`

	// ToolCallMode controls how the agent invokes tools.
	// "auto" (default): auto-detect via model capabilities
	// "native": force native OpenAI function calling
	// "string": force text-based JSON tool calling
	// +kubebuilder:validation:Enum=auto;native;string
	// +kubebuilder:default=auto
	// +kubebuilder:validation:Optional
	ToolCallMode string `json:"toolCallMode,omitempty"`

	// Memory configures the agent's memory system
	// +kubebuilder:validation:Optional
	Memory *MemoryConfig `json:"memory,omitempty"`

	// Telemetry configures OpenTelemetry instrumentation
	// +kubebuilder:validation:Optional
	Telemetry *TelemetryConfig `json:"telemetry,omitempty"`

	// Autonomous configures autonomous (self-looping) execution.
	// Setting a goal activates autonomous mode on agent startup.
	// +kubebuilder:validation:Optional
	Autonomous *AutonomousConfig `json:"autonomous,omitempty"`

	// TaskConfig configures budget limits for A2A async tasks
	// +kubebuilder:validation:Optional
	TaskConfig *TaskConfig `json:"taskConfig,omitempty"`
}

// +kubebuilder:object:generate=true

// AutonomousConfig configures autonomous (self-looping) agent execution.
// When a goal is set, the agent self-loops on startup with per-iteration budgets.
// For bounded async tasks triggered via A2A, use taskConfig.
type AutonomousConfig struct {
	// Goal is the objective the agent works toward autonomously.
	// Setting this activates autonomous execution on agent startup.
	// +optional
	Goal string `json:"goal,omitempty"`

	// IntervalSeconds is the pause between autonomous loop iterations (default: 0, no pause)
	// +optional
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=3600
	IntervalSeconds *int32 `json:"intervalSeconds,omitempty"`

	// MaxIterRuntimeSeconds is the maximum wall-clock time per iteration (default: 60, 0 = unlimited)
	// +optional
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=86400
	MaxIterRuntimeSeconds *int32 `json:"maxIterRuntimeSeconds,omitempty"`
}

// +kubebuilder:object:generate=true

// TaskConfig configures budget limits for A2A async task execution.
type TaskConfig struct {
	// MaxIterations is the max iterations for A2A async tasks (default: 10, 0 = unlimited)
	// +optional
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=1000
	MaxIterations *int32 `json:"maxIterations,omitempty"`

	// MaxRuntimeSeconds is the max wall-clock time for A2A async tasks (default: 300, 0 = unlimited)
	// +optional
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=86400
	MaxRuntimeSeconds *int32 `json:"maxRuntimeSeconds,omitempty"`

	// MaxToolCalls is the max cumulative tool calls for A2A async tasks (default: 50, 0 = unlimited)
	// +optional
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=10000
	MaxToolCalls *int32 `json:"maxToolCalls,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentSpec defines the desired state of Agent
type AgentSpec struct {
	// ModelAPI is the name of the ModelAPI resource this agent uses
	ModelAPI string `json:"modelAPI"`

	// Model is the model identifier this agent uses (e.g., "openai/gpt-4", "ollama/smollm2:135m")
	// Must be supported by the referenced ModelAPI
	Model string `json:"model"`

	// MCPServers is a list of MCPServer names this agent can use
	// +kubebuilder:validation:Optional
	MCPServers []string `json:"mcpServers,omitempty"`

	// AgentNetwork defines A2A communication settings
	// +kubebuilder:validation:Optional
	AgentNetwork *AgentNetworkConfig `json:"agentNetwork,omitempty"`

	// Config contains agent-specific configuration
	// +kubebuilder:validation:Optional
	Config *AgentConfig `json:"config,omitempty"`

	// WaitForDependencies controls whether the agent waits for ModelAPI and MCPServers to be ready
	// before creating the deployment. Default is true.
	// +kubebuilder:default=true
	WaitForDependencies *bool `json:"waitForDependencies,omitempty"`

	// GatewayRoute configures Gateway API routing (timeout, etc.)
	// +kubebuilder:validation:Optional
	GatewayRoute *GatewayRoute `json:"gatewayRoute,omitempty"`

	// Container provides shorthand container overrides (image, env, resources)
	// +kubebuilder:validation:Optional
	Container *ContainerOverride `json:"container,omitempty"`

	// PodSpec allows overriding the generated pod spec using strategic merge patch
	// +kubebuilder:validation:Optional
	PodSpec *corev1.PodSpec `json:"podSpec,omitempty"`
}

// +kubebuilder:object:generate=true

// AgentStatus defines the observed state of Agent
type AgentStatus struct {
	// Phase of the deployment
	// +kubebuilder:validation:Enum=Pending;Ready;Failed;Waiting
	Phase string `json:"phase,omitempty"`

	// Ready indicates if the agent is ready
	Ready bool `json:"ready,omitempty"`

	// Endpoint is the Agent Card HTTP endpoint for A2A communication
	// +kubebuilder:validation:Optional
	Endpoint string `json:"endpoint,omitempty"`

	// LinkedResources tracks references to ModelAPI and MCPServer resources
	// +kubebuilder:validation:Optional
	LinkedResources map[string]string `json:"linkedResources,omitempty"`

	// Message provides additional status information
	Message string `json:"message,omitempty"`

	// Conditions represent the latest available observations of the agent's state.
	// The MemoryDegraded condition is set when a bound MemoryStore is not Ready
	// while the agent continues serving short-term-only memory.
	// +kubebuilder:validation:Optional
	// +listType=map
	// +listMapKey=type
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// Deployment contains status information from the underlying Deployment
	// +kubebuilder:validation:Optional
	Deployment *DeploymentStatus `json:"deployment,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=agent;agents
// +kubebuilder:printcolumn:name="ModelAPI",type=string,JSONPath=`.spec.modelAPI`
// +kubebuilder:printcolumn:name="Model",type=string,JSONPath=`.spec.model`
// +kubebuilder:printcolumn:name="Ready",type=boolean,JSONPath=`.status.ready`
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`

// Agent is the Schema for the agents API
type Agent struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   AgentSpec   `json:"spec,omitempty"`
	Status AgentStatus `json:"status,omitempty"`
}

// IsAutonomous reports whether the agent has a non-empty autonomous goal.
// The runtime uses the same goal-is-non-empty rule so both layers stay aligned.
func (a *Agent) IsAutonomous() bool {
	return a != nil && a.Spec.Config != nil && a.Spec.Config.Autonomous != nil && strings.TrimSpace(a.Spec.Config.Autonomous.Goal) != ""
}

// +kubebuilder:object:root=true

// AgentList contains a list of Agent
type AgentList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Agent `json:"items"`
}

func init() {
	SchemeBuilder.Register(&Agent{}, &AgentList{})
}
