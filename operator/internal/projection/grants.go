package projection

import "sort"

// GrantData is the Model-1 authorization data projected from the grant graph:
// a map from an actor's logical identity (the agent external id, which the
// broker stamps as the actor token `sub`) to the sorted set of resource logical
// identities that actor is allowed to reach. It is what the operator serializes
// into `data.kaos.grants` for the enforcement policy to match a request against.
//
// It is pure and derived entirely from the DesiredState grant graph, so the same
// projection feeds both the broker admin adapter (Model 2) and this data (Model
// 1) without re-deriving relationships.
func GrantData(state DesiredState) map[string][]string {
	permissionSetsByName := make(map[string]DesiredPermissionSet, len(state.PermissionSets))
	for _, ps := range state.PermissionSets {
		permissionSetsByName[ps.Name()] = ps
	}

	grants := make(map[string][]string, len(state.Agents))
	for _, agent := range state.Agents {
		seen := make(map[string]bool, len(agent.PermissionSetNames))
		resources := make([]string, 0, len(agent.PermissionSetNames))
		for _, name := range agent.PermissionSetNames {
			ps, ok := permissionSetsByName[name]
			if !ok {
				continue
			}
			resource := ps.ResourceID()
			if seen[resource] {
				continue
			}
			seen[resource] = true
			resources = append(resources, resource)
		}
		sort.Strings(resources)
		grants[agent.ExternalID()] = resources
	}
	return grants
}
