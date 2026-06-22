package identity

import "testing"

func TestResolveDefaultNamespaceScoped(t *testing.T) {
	cases := []struct {
		kind Kind
		want string
	}{
		{KindAgent, "kaos://agent/demo/researcher"},
		{KindMCPServer, "kaos://mcpserver/demo/researcher"},
		{KindModelAPI, "kaos://modelapi/demo/researcher"},
	}
	for _, c := range cases {
		if got := Resolve(c.kind, "demo", "researcher", ""); got != c.want {
			t.Errorf("Resolve(%s, demo, researcher, \"\") = %q, want %q", c.kind, got, c.want)
		}
	}
}

func TestResolveExplicitIDNamespaceIndependent(t *testing.T) {
	cases := []struct {
		kind Kind
		id   string
		want string
	}{
		{KindAgent, "researcher", "kaos://agent/researcher"},
		{KindMCPServer, "shared-tools", "kaos://mcpserver/shared-tools"},
		{KindModelAPI, "team.gpt4", "kaos://modelapi/team.gpt4"},
	}
	for _, c := range cases {
		if got := Resolve(c.kind, "demo", "ignored", c.id); got != c.want {
			t.Errorf("Resolve(%s, demo, ignored, %q) = %q, want %q", c.kind, c.id, got, c.want)
		}
	}
}

func TestResolveExplicitIDIgnoresNamespaceAndName(t *testing.T) {
	a := Resolve(KindAgent, "ns-a", "name-a", "stable")
	b := Resolve(KindAgent, "ns-b", "name-b", "stable")
	if a != b {
		t.Errorf("explicit id should be namespace/name independent: %q != %q", a, b)
	}
}
