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
		{name: "agent override", mem: &kaosv1alpha1.MemoryConfig{Scope: "user"}, store: &kaosv1alpha1.MemoryStore{Spec: kaosv1alpha1.MemoryStoreSpec{DefaultScope: "group"}}, want: "user"},
		{name: "store default", mem: &kaosv1alpha1.MemoryConfig{}, store: &kaosv1alpha1.MemoryStore{Spec: kaosv1alpha1.MemoryStoreSpec{DefaultScope: "group"}}, want: "group"},
		{name: "agent fallback", mem: &kaosv1alpha1.MemoryConfig{}, store: &kaosv1alpha1.MemoryStore{}, want: "agent"},
		{name: "missing store", mem: &kaosv1alpha1.MemoryConfig{}, want: "agent"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := resolveMemoryScope(tt.mem, tt.store); got != tt.want {
				t.Fatalf("resolveMemoryScope() = %q, want %q", got, tt.want)
			}
		})
	}
}
