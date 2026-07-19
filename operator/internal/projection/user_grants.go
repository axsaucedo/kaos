package projection

import (
	"sort"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
)

var resourceKinds = map[string]EdgeKind{
	Agent.ResourceKind:       Agent,
	MCPServer.ResourceKind:   MCPServer,
	ModelAPI.ResourceKind:    ModelAPI,
	MemoryStore.ResourceKind: MemoryStore,
}

// UserGrantData compiles namespaced AccessGrants into subject-to-resource data.
func UserGrantData(state DesiredState) map[string][]string {
	sets := map[string]map[string]struct{}{}
	for _, grant := range state.AccessGrants {
		resources := resolveGrantResources(grant, state.Resources)
		for _, subject := range grant.Subjects {
			if subject.Kind == "Agent" {
				continue
			}
			prefix := "user:"
			if subject.Kind == "Group" {
				prefix = "group:"
			}
			key := prefix + subject.Name
			if sets[key] == nil {
				sets[key] = map[string]struct{}{}
			}
			for _, resource := range resources {
				sets[key][resource] = struct{}{}
			}
		}
	}

	out := make(map[string][]string, len(sets))
	for subject, set := range sets {
		for resource := range set {
			out[subject] = append(out[subject], resource)
		}
		sort.Strings(out[subject])
	}
	return out
}

func resolveGrantResources(grant AccessGrant, resources []Resource) []string {
	set := map[string]struct{}{}
	for _, ref := range grant.Resources {
		if ref.Selector == nil {
			if kind, ok := resourceKinds[ref.Kind]; ok {
				set[ResolveLogicalID(kind.Slug, grant.Namespace, ref.Name)] = struct{}{}
			}
			continue
		}
		selector, err := metav1.LabelSelectorAsSelector(ref.Selector)
		if err != nil {
			continue
		}
		for _, resource := range resources {
			kind, ok := resourceKinds[resource.Kind]
			if ok && resource.Namespace == grant.Namespace && selector.Matches(labels.Set(resource.Labels)) {
				set[ResolveLogicalID(kind.Slug, resource.Namespace, resource.Name)] = struct{}{}
			}
		}
	}
	out := make([]string, 0, len(set))
	for resource := range set {
		out = append(out, resource)
	}
	return out
}
