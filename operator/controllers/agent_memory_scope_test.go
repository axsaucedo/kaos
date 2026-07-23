package controllers

import (
	"testing"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
)

func TestResolveMemoryScope(t *testing.T) {
	tests := []struct {
		name  string
		mem   *kaosv1alpha1.MemoryConfig
		store *kaosv1alpha1.MemoryStore
		want  string
	}{
		{name: "agent override", mem: &kaosv1alpha1.MemoryConfig{MaxReadScope: "user"}, store: &kaosv1alpha1.MemoryStore{Spec: kaosv1alpha1.MemoryStoreSpec{MaxReadScope: "user"}}, want: "user"},
		{name: "store ceiling", mem: &kaosv1alpha1.MemoryConfig{}, store: &kaosv1alpha1.MemoryStore{Spec: kaosv1alpha1.MemoryStoreSpec{MaxReadScope: "user"}}, want: "user"},
		{name: "store default", mem: &kaosv1alpha1.MemoryConfig{}, store: &kaosv1alpha1.MemoryStore{}, want: "agent"},
		{name: "missing store", mem: &kaosv1alpha1.MemoryConfig{}, want: "session"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := resolveMaxReadScope(tt.mem, tt.store); got != tt.want {
				t.Fatalf("resolveMaxReadScope() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestReadScopeRank(t *testing.T) {
	if !(readScopeRank("session") < readScopeRank("agent") && readScopeRank("agent") < readScopeRank("user")) {
		t.Fatal("read scope ordering must be session < agent < user")
	}
}
