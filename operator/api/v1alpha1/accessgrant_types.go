package v1alpha1

import metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

// AccessGrantSubjectKind identifies the kind of identity matched by a subject.
type AccessGrantSubjectKind string

const (
	// AccessGrantSubjectKindUser matches the token subject or email claim.
	AccessGrantSubjectKindUser AccessGrantSubjectKind = "User"
	// AccessGrantSubjectKindGroup matches an entry in the token groups claim.
	AccessGrantSubjectKindGroup AccessGrantSubjectKind = "Group"
	// AccessGrantSubjectKindAgent grants an agent access to another KAOS resource.
	AccessGrantSubjectKindAgent AccessGrantSubjectKind = "Agent"
)

// AccessGrantResourceKind identifies a KAOS resource kind.
type AccessGrantResourceKind string

const (
	AccessGrantResourceKindAgent       AccessGrantResourceKind = "Agent"
	AccessGrantResourceKindMCPServer   AccessGrantResourceKind = "MCPServer"
	AccessGrantResourceKindModelAPI    AccessGrantResourceKind = "ModelAPI"
	AccessGrantResourceKindMemoryStore AccessGrantResourceKind = "MemoryStore"
)

// AccessGrantSubject identifies a user, group, or agent receiving access.
type AccessGrantSubject struct {
	// Kind specifies whether Name identifies a user, group, or agent.
	// +kubebuilder:validation:Enum=User;Group;Agent
	Kind AccessGrantSubjectKind `json:"kind"`

	// Name is a token claim value for users/groups or a KAOS Agent name.
	// +kubebuilder:validation:MinLength=1
	Name string `json:"name"`
}

// AccessGrantResource identifies resources by explicit reference or label selector.
// Exactly one form must be set: Kind and Name together, or Selector.
type AccessGrantResource struct {
	// Kind is the kind of an explicitly referenced resource.
	// +kubebuilder:validation:Enum=Agent;MCPServer;ModelAPI;MemoryStore
	// +optional
	Kind AccessGrantResourceKind `json:"kind,omitempty"`

	// Name is the name of an explicitly referenced resource.
	// +optional
	Name string `json:"name,omitempty"`

	// Selector matches resources by label.
	// +optional
	Selector *metav1.LabelSelector `json:"selector,omitempty"`
}

// AccessGrantSpec defines user-to-resource authorization bindings.
type AccessGrantSpec struct {
	// Subjects identifies the users, groups, and agents receiving access.
	// +kubebuilder:validation:MinItems=1
	Subjects []AccessGrantSubject `json:"subjects"`

	// Resources identifies the resources subjects may access.
	// +kubebuilder:validation:MinItems=1
	Resources []AccessGrantResource `json:"resources"`
}

// AccessGrantStatus defines the observed enforcement state of an AccessGrant.
type AccessGrantStatus struct {
	// Conditions represent the latest available observations of the grant's state.
	// The Enforced condition uses reasons Enforced, NoUserIdentityProvider,
	// PolicyProjectionInactive, ProjectionFailed, or AuthorizationDisabled.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// AccessGrant is the Schema for the accessgrants API.
type AccessGrant struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   AccessGrantSpec   `json:"spec,omitempty"`
	Status AccessGrantStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// AccessGrantList contains a list of AccessGrant resources.
type AccessGrantList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []AccessGrant `json:"items"`
}

func init() {
	SchemeBuilder.Register(&AccessGrant{}, &AccessGrantList{})
}
