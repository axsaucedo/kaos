package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ThirdPartyServiceEndpoints overrides OAuth endpoints when issuer discovery is unavailable.
type ThirdPartyServiceEndpoints struct {
	// Token is the provider's OAuth token endpoint.
	// +kubebuilder:validation:Pattern=`^https?://`
	Token string `json:"token"`

	// Authorization is the provider's OAuth authorization endpoint.
	// +kubebuilder:validation:Pattern=`^https?://`
	Authorization string `json:"authorization"`
}

// ThirdPartyServiceScope is an OAuth scope exposed by the third-party service.
type ThirdPartyServiceScope struct {
	// Name is the provider scope value.
	// +kubebuilder:validation:MinLength=1
	Name string `json:"name"`

	// Description explains what the scope permits.
	// +optional
	Description string `json:"description,omitempty"`
}

// ThirdPartyServiceAccess binds one namespaced Agent to provider scopes.
type ThirdPartyServiceAccess struct {
	// Agent is the name of an Agent in this namespace.
	// +kubebuilder:validation:MinLength=1
	Agent string `json:"agent"`

	// Scopes is the subset of service scopes granted to the Agent.
	// +kubebuilder:validation:MinItems=1
	Scopes []string `json:"scopes"`
}

// ThirdPartyServiceRouteRef identifies the namespaced third-party egress HTTPRoute.
type ThirdPartyServiceRouteRef struct {
	// Name is the HTTPRoute that carries only this service's external traffic.
	// +kubebuilder:validation:MinLength=1
	Name string `json:"name"`
}

// ThirdPartyServiceSpec declares an OAuth service and the agents allowed to use it.
type ThirdPartyServiceSpec struct {
	// DisplayName is the human-readable provider name. It defaults to metadata.name.
	// +optional
	DisplayName string `json:"displayName,omitempty"`

	// ClientID is the OAuth client registered with the third-party provider.
	// +kubebuilder:validation:MinLength=1
	ClientID string `json:"clientID"`

	// ClientSecretRef references the provider OAuth client secret.
	ClientSecretRef corev1.SecretKeySelector `json:"clientSecretRef"`

	// IssuerURI is the third-party OAuth issuer. AIB uses discovery when Endpoints is omitted.
	// +kubebuilder:validation:Pattern=`^https?://`
	IssuerURI string `json:"issuerURI"`

	// Endpoints explicitly configures OAuth endpoints when the issuer has no discovery document.
	// +optional
	Endpoints *ThirdPartyServiceEndpoints `json:"endpoints,omitempty"`

	// Scopes lists the OAuth scopes this declaration may grant.
	// +kubebuilder:validation:MinItems=1
	// +listType=map
	// +listMapKey=name
	Scopes []ThirdPartyServiceScope `json:"scopes"`

	// ProtectedResources lists external resource URLs whose credentials AIB may exchange.
	// +kubebuilder:validation:MinItems=1
	ProtectedResources []string `json:"protectedResources"`

	// RouteRef identifies the dedicated third-party egress HTTPRoute. Internal KAOS routes are never selected implicitly.
	RouteRef ThirdPartyServiceRouteRef `json:"routeRef"`

	// Access declares real Agent-to-service scope bindings.
	// +kubebuilder:validation:MinItems=1
	// +listType=map
	// +listMapKey=agent
	Access []ThirdPartyServiceAccess `json:"access"`
}

// ThirdPartyServiceStatus reports token-exchange projection and route attachment.
type ThirdPartyServiceStatus struct {
	// Conditions represent the latest observations of the service integration.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=tps
// +kubebuilder:printcolumn:name="Issuer",type=string,JSONPath=`.spec.issuerURI`
// +kubebuilder:printcolumn:name="Route",type=string,JSONPath=`.spec.routeRef.name`

// ThirdPartyService declares an external OAuth service and namespaced Agent bindings.
type ThirdPartyService struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ThirdPartyServiceSpec   `json:"spec,omitempty"`
	Status ThirdPartyServiceStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// ThirdPartyServiceList contains a list of ThirdPartyService resources.
type ThirdPartyServiceList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ThirdPartyService `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ThirdPartyService{}, &ThirdPartyServiceList{})
}
