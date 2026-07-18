package v1alpha1

import "testing"

func TestAgentIsAutonomous(t *testing.T) {
	tests := []struct {
		name  string
		agent *Agent
		want  bool
	}{
		{name: "goal set", agent: &Agent{Spec: AgentSpec{Config: &AgentConfig{Autonomous: &AutonomousConfig{Goal: "Investigate"}}}}, want: true},
		{name: "blank goal", agent: &Agent{Spec: AgentSpec{Config: &AgentConfig{Autonomous: &AutonomousConfig{Goal: "  "}}}}},
		{name: "nil config", agent: &Agent{}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tt.agent.IsAutonomous(); got != tt.want {
				t.Fatalf("IsAutonomous() = %v, want %v", got, tt.want)
			}
		})
	}
}
