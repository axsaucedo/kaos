package adapters

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	gatewayv1 "sigs.k8s.io/gateway-api/apis/v1"

	"github.com/axsaucedo/kaos/operator/internal/projection"
	"github.com/axsaucedo/kaos/operator/pkg/gateway"
	"github.com/axsaucedo/kaos/operator/pkg/security"
)

const (
	exchangeReflectionName = "kaos-token-exchange-reflection"
	exchangeManagedLabel   = "kaos.tools/token-exchange-managed"
	exchangeRouteLabel     = "kaos.tools/token-exchange-route"
	exchangeServiceIDLabel = "kaos.tools/token-exchange-service-id"
	exchangeSourceNSLabel  = "kaos.tools/token-exchange-source-namespace"
	exchangeFieldOwner     = "kaos-token-exchange-reflector"
	legacyAIBAgentIDPrefix = "kaos://agent/"
	extensionPolicyGroup   = "gateway.envoyproxy.io"
	extensionPolicyVersion = "v1alpha1"
	extensionPolicyKind    = "EnvoyExtensionPolicy"
	backendKind            = "Backend"
	backendVersion         = "v1alpha1"
	referenceGrantVersion  = "v1beta1"
)

var (
	extensionPolicyGVK = schema.GroupVersionKind{Group: extensionPolicyGroup, Version: extensionPolicyVersion, Kind: extensionPolicyKind}
	backendGVK         = schema.GroupVersionKind{Group: extensionPolicyGroup, Version: backendVersion, Kind: backendKind}
	referenceGrantGVK  = schema.GroupVersionKind{Group: "gateway.networking.k8s.io", Version: referenceGrantVersion, Kind: "ReferenceGrant"}
)

// AIBExchangeAdmin is the read/update subset used by AIB-native reflection.
// Services and permission sets are administrator-owned and are never written.
type AIBExchangeAdmin interface {
	List(context.Context, string) ([]map[string]any, error)
	ListAgents(context.Context) ([]map[string]any, error)
	Update(context.Context, string, string, map[string]any) error
}

// ExchangeProjector reflects AIB-administered bindings into cluster egress
// plumbing and keeps existing AIB Agent records keyed to current OIDC clients.
type ExchangeProjector struct {
	Client           client.Client
	Scheme           *runtime.Scheme
	AIB              AIBExchangeAdmin
	Enabled          bool
	OIDCSecretPrefix string
	ExtProcName      string
	ExtProcNamespace string
	ExtProcPort      int
}

type exchangeService struct {
	ID        string
	Resources []string
	Origins   []exchangeOrigin
}

type exchangeOrigin struct {
	Scheme   string
	Hostname string
	Port     int
}

func (o exchangeOrigin) key() string {
	return fmt.Sprintf("%s://%s:%d", o.Scheme, o.Hostname, o.Port)
}

type reflectedNamespace struct {
	Targets  map[string][]string
	Services map[string]exchangeService
}

// Apply performs a read-first, fail-static reflection pass. AIB read or schema
// failures happen before any Kubernetes state is changed.
func (p *ExchangeProjector) Apply(ctx context.Context, desired projection.DesiredState) error {
	if !p.Enabled {
		return nil
	}
	agents, err := p.AIB.ListAgents(ctx)
	if err != nil {
		return fmt.Errorf("listing AIB agents: %w", err)
	}
	services, err := p.AIB.List(ctx, "services")
	if err != nil {
		return fmt.Errorf("listing AIB services: %w", err)
	}
	permissionSets, err := p.AIB.List(ctx, "permission-sets")
	if err != nil {
		return fmt.Errorf("listing AIB permission sets: %w", err)
	}

	desiredAgents := make(map[string]projection.DesiredAgent, len(desired.Agents))
	for _, agent := range desired.Agents {
		desiredAgents[projection.AIBAgentExternalID(agent.Namespace, agent.Name)] = agent
	}
	if err := p.refreshAgentIDs(ctx, desiredAgents, agents); err != nil {
		return err
	}

	state, err := buildReflection(desiredAgents, agents, services, permissionSets)
	if err != nil {
		return err
	}
	return p.reconcile(ctx, state)
}

// refreshAgentIDs preserves administrator-owned permission-set bindings while
// migrating legacy IDs and updating the Keycloak DCR client UUID.
func (p *ExchangeProjector) refreshAgentIDs(ctx context.Context, desired map[string]projection.DesiredAgent, agents []map[string]any) error {
	var errs []error
	for _, record := range agents {
		externalID := stringField(record, "external_id")
		stableID := externalID
		if strings.HasPrefix(externalID, legacyAIBAgentIDPrefix) {
			stableID = "kaos/" + strings.TrimPrefix(externalID, legacyAIBAgentIDPrefix)
		}
		agent, ok := desired[stableID]
		if !ok {
			continue
		}
		clientID, err := p.agentClientID(ctx, agent.Namespace, agent.Name)
		if err != nil {
			errs = append(errs, err)
			continue
		}
		if externalID == stableID && stringField(record, "client_id") == clientID {
			continue
		}
		id := stringField(record, "id")
		if id == "" {
			errs = append(errs, fmt.Errorf("AIB agent %q has no id", externalID))
			continue
		}
		body := agentUpdateBody(record)
		body["external_id"] = stableID
		body["client_id"] = clientID
		if err := p.AIB.Update(ctx, "agents", id, body); err != nil {
			errs = append(errs, fmt.Errorf("updating AIB agent %q: %w", stableID, err))
			continue
		}
		record["external_id"] = stableID
		record["client_id"] = clientID
	}
	return errors.Join(errs...)
}

func agentUpdateBody(record map[string]any) map[string]any {
	body := map[string]any{}
	for _, field := range []string{
		"client_id", "external_id", "display_name", "description", "governance_url",
		"user_documentation_url", "agent_interface_url", "service_requirements",
		"permission_sets", "redirect_uris", "allowed_scopes", "client_uris",
	} {
		if value, ok := record[field]; ok {
			body[field] = value
		}
	}
	return body
}

func buildReflection(desiredAgents map[string]projection.DesiredAgent, agents, rawServices, rawPermissionSets []map[string]any) (map[string]reflectedNamespace, error) {
	services := make(map[string]exchangeService, len(rawServices))
	for _, raw := range rawServices {
		service, err := parseExchangeService(raw)
		if err != nil {
			return nil, err
		}
		services[service.ID] = service
	}
	permissionServices := make(map[string][]string, len(rawPermissionSets))
	for _, permissionSet := range rawPermissionSets {
		id := stringField(permissionSet, "id")
		if id == "" {
			return nil, fmt.Errorf("AIB permission set has no id")
		}
		for _, scope := range objectSlice(permissionSet["service_scopes"]) {
			serviceID := stringField(scope, "service_id")
			if serviceID == "" {
				return nil, fmt.Errorf("AIB permission set %q has a service scope without service_id", id)
			}
			permissionServices[id] = append(permissionServices[id], serviceID)
		}
	}

	state := map[string]reflectedNamespace{}
	for _, rawAgent := range agents {
		externalID := stringField(rawAgent, "external_id")
		agent, ok := desiredAgents[externalID]
		if !ok {
			continue
		}
		serviceIDs := map[string]bool{}
		for _, permission := range objectSlice(rawAgent["permission_sets"]) {
			for _, serviceID := range permissionServices[stringField(permission, "permission_set_id")] {
				serviceIDs[serviceID] = true
			}
		}
		ns := state[agent.Namespace]
		if ns.Targets == nil {
			ns.Targets = map[string][]string{}
			ns.Services = map[string]exchangeService{}
		}
		for serviceID := range serviceIDs {
			service, ok := services[serviceID]
			if !ok {
				return nil, fmt.Errorf("AIB agent %q references permission set service %q that does not exist", externalID, serviceID)
			}
			ns.Targets[agent.Name] = append(ns.Targets[agent.Name], service.Resources...)
			ns.Services[serviceID] = service
		}
		state[agent.Namespace] = ns
	}
	for namespace, ns := range state {
		for agent, targets := range ns.Targets {
			ns.Targets[agent] = uniqueSorted(targets)
		}
		state[namespace] = ns
	}
	return state, nil
}

func parseExchangeService(raw map[string]any) (exchangeService, error) {
	id := stringField(raw, "id")
	if id == "" {
		return exchangeService{}, fmt.Errorf("AIB service has no id")
	}
	resources := stringSlice(raw["protected_resources"])
	if len(resources) == 0 {
		return exchangeService{}, fmt.Errorf("AIB service %q has no protected_resources", id)
	}
	origins := map[string]exchangeOrigin{}
	for _, resource := range resources {
		parsed, err := url.Parse(resource)
		if err != nil || parsed.Hostname() == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
			return exchangeService{}, fmt.Errorf("AIB service %q has invalid protected resource %q", id, resource)
		}
		port := 80
		if parsed.Scheme == "https" {
			port = 443
		}
		if parsed.Port() != "" {
			if _, err := fmt.Sscanf(parsed.Port(), "%d", &port); err != nil || port < 1 || port > 65535 {
				return exchangeService{}, fmt.Errorf("AIB service %q has invalid protected resource port %q", id, resource)
			}
		}
		origin := exchangeOrigin{Scheme: parsed.Scheme, Hostname: parsed.Hostname(), Port: port}
		origins[origin.key()] = origin
	}
	service := exchangeService{ID: id, Resources: uniqueSorted(resources)}
	for _, origin := range origins {
		service.Origins = append(service.Origins, origin)
	}
	sort.Slice(service.Origins, func(i, j int) bool { return service.Origins[i].key() < service.Origins[j].key() })
	return service, nil
}

func (p *ExchangeProjector) reconcile(ctx context.Context, state map[string]reflectedNamespace) error {
	desiredObjects := map[types.NamespacedName]bool{}
	for namespace, ns := range state {
		anchor, err := p.reconcileAnchor(ctx, namespace, ns.Targets)
		if err != nil {
			return err
		}
		for _, service := range ns.Services {
			for _, origin := range service.Origins {
				name := exchangeRouteName(service.ID, origin)
				key := types.NamespacedName{Namespace: namespace, Name: name}
				desiredObjects[key] = true
				if err := p.reconcileOrigin(ctx, anchor, service.ID, origin, name); err != nil {
					return err
				}
			}
		}
	}
	return p.prune(ctx, state, desiredObjects)
}

func (p *ExchangeProjector) reconcileAnchor(ctx context.Context, namespace string, targets map[string][]string) (*corev1.ConfigMap, error) {
	data := make(map[string]string, len(targets))
	for agent, values := range targets {
		encoded, _ := json.Marshal(values)
		data[agent] = string(encoded)
	}
	anchor := &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: exchangeReflectionName, Namespace: namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, p.Client, anchor, func() error {
		anchor.Labels = managedLabels("")
		anchor.Data = data
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("reconciling exchange reflection ConfigMap %s/%s: %w", namespace, exchangeReflectionName, err)
	}
	return anchor, nil
}

func (p *ExchangeProjector) reconcileOrigin(ctx context.Context, owner *corev1.ConfigMap, serviceID string, origin exchangeOrigin, name string) error {
	backend := constructExchangeBackend(owner.Namespace, serviceID, origin, name)
	if err := controllerutil.SetControllerReference(owner, backend, p.Scheme); err != nil {
		return err
	}
	if err := applyUnstructured(ctx, p.Client, backend); err != nil {
		return fmt.Errorf("reconciling Backend %s/%s: %w", owner.Namespace, name, err)
	}

	route := constructExchangeRoute(owner.Namespace, serviceID, origin, name, gateway.GetConfig())
	if err := controllerutil.SetControllerReference(owner, route, p.Scheme); err != nil {
		return err
	}
	if err := p.Client.Patch(ctx, route, client.Apply, client.FieldOwner(exchangeFieldOwner), client.ForceOwnership); err != nil {
		return fmt.Errorf("reconciling HTTPRoute %s/%s: %w", owner.Namespace, name, err)
	}

	policy, err := constructExtProcPolicy(route, p.ExtProcName, p.ExtProcNamespace, p.ExtProcPort)
	if err != nil {
		return err
	}
	if err := controllerutil.SetControllerReference(owner, policy, p.Scheme); err != nil {
		return err
	}
	if err := applyUnstructured(ctx, p.Client, policy); err != nil {
		return fmt.Errorf("reconciling EnvoyExtensionPolicy %s/%s: %w", owner.Namespace, name, err)
	}
	if p.ExtProcNamespace != "" && p.ExtProcNamespace != owner.Namespace {
		if err := reconcileExtProcReferenceGrant(ctx, p.Client, owner.Namespace, p.ExtProcNamespace, p.ExtProcName); err != nil {
			return err
		}
	}
	return nil
}

func constructExchangeBackend(namespace, serviceID string, origin exchangeOrigin, name string) *unstructured.Unstructured {
	backend := &unstructured.Unstructured{}
	backend.SetGroupVersionKind(backendGVK)
	backend.SetName(name)
	backend.SetNamespace(namespace)
	backend.SetLabels(managedLabels(serviceID))
	spec := map[string]any{
		"endpoints": []any{map[string]any{"fqdn": map[string]any{"hostname": origin.Hostname, "port": int64(origin.Port)}}},
	}
	if origin.Scheme == "https" {
		spec["tls"] = map[string]any{"wellKnownCACertificates": "System"}
	}
	backend.Object["spec"] = spec
	return backend
}

func constructExchangeRoute(namespace, serviceID string, origin exchangeOrigin, name string, cfg gateway.Config) *gatewayv1.HTTPRoute {
	group := gatewayv1.Group(extensionPolicyGroup)
	kind := gatewayv1.Kind(backendKind)
	gwNamespace := gatewayv1.Namespace(cfg.GatewayNamespace)
	return &gatewayv1.HTTPRoute{
		TypeMeta:   metav1.TypeMeta{APIVersion: gatewayv1.GroupVersion.String(), Kind: "HTTPRoute"},
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace, Labels: managedRouteLabels(serviceID)},
		Spec: gatewayv1.HTTPRouteSpec{
			CommonRouteSpec: gatewayv1.CommonRouteSpec{ParentRefs: []gatewayv1.ParentReference{{Name: gatewayv1.ObjectName(cfg.GatewayName), Namespace: &gwNamespace}}},
			Hostnames:       []gatewayv1.Hostname{gatewayv1.Hostname(origin.Hostname)},
			Rules:           []gatewayv1.HTTPRouteRule{{BackendRefs: []gatewayv1.HTTPBackendRef{{BackendRef: gatewayv1.BackendRef{BackendObjectReference: gatewayv1.BackendObjectReference{Group: &group, Kind: &kind, Name: gatewayv1.ObjectName(name)}}}}}},
		},
	}
}

// constructExtProcPolicy accepts only routes created by this reflector. This is
// the safe-by-construction boundary that prevents attachment to internal routes.
func constructExtProcPolicy(route *gatewayv1.HTTPRoute, backendName, backendNamespace string, backendPort int) (*unstructured.Unstructured, error) {
	if route.Labels[exchangeRouteLabel] != "true" || route.Labels[exchangeManagedLabel] != "true" {
		return nil, fmt.Errorf("ext_proc can target only operator-generated third-party egress routes")
	}
	if backendName == "" || backendNamespace == "" || backendPort <= 0 {
		return nil, fmt.Errorf("AIB ext_proc backend is incomplete")
	}
	policy := &unstructured.Unstructured{}
	policy.SetGroupVersionKind(extensionPolicyGVK)
	policy.SetName(route.Name)
	policy.SetNamespace(route.Namespace)
	policy.SetLabels(route.Labels)
	policy.Object["spec"] = map[string]any{
		"targetRefs": []any{map[string]any{"group": "gateway.networking.k8s.io", "kind": "HTTPRoute", "name": route.Name}},
		"extProc": []any{map[string]any{
			"backendRefs": []any{map[string]any{"group": "", "kind": "Service", "name": backendName, "namespace": backendNamespace, "port": int64(backendPort)}},
			"failOpen":    false, "processingMode": map[string]any{"request": map[string]any{}},
		}},
	}
	return policy, nil
}

func reconcileExtProcReferenceGrant(ctx context.Context, c client.Client, sourceNamespace, backendNamespace, serviceName string) error {
	hash := sha256.Sum256([]byte(sourceNamespace + "\x00" + serviceName))
	grant := &unstructured.Unstructured{}
	grant.SetGroupVersionKind(referenceGrantGVK)
	grant.SetName(fmt.Sprintf("kaos-ext-proc-%x", hash[:6]))
	grant.SetNamespace(backendNamespace)
	labels := managedLabels("")
	labels[exchangeSourceNSLabel] = sourceNamespace
	grant.SetLabels(labels)
	grant.Object["spec"] = map[string]any{
		"from": []any{map[string]any{"group": extensionPolicyGroup, "kind": extensionPolicyKind, "namespace": sourceNamespace}},
		"to":   []any{map[string]any{"group": "", "kind": "Service", "name": serviceName}},
	}
	return applyUnstructured(ctx, c, grant)
}

func applyUnstructured(ctx context.Context, c client.Client, object *unstructured.Unstructured) error {
	return c.Patch(ctx, object, client.Apply, client.FieldOwner(exchangeFieldOwner), client.ForceOwnership)
}

func (p *ExchangeProjector) prune(ctx context.Context, state map[string]reflectedNamespace, desired map[types.NamespacedName]bool) error {
	anchors := &corev1.ConfigMapList{}
	if err := p.Client.List(ctx, anchors, client.MatchingLabels{exchangeManagedLabel: "true"}); err != nil {
		return err
	}
	for i := range anchors.Items {
		anchor := &anchors.Items[i]
		if anchor.Name == exchangeReflectionName {
			if _, ok := state[anchor.Namespace]; !ok {
				if err := p.Client.Delete(ctx, anchor); err != nil && !apierrors.IsNotFound(err) {
					return err
				}
			}
		}
	}
	for _, gvk := range []schema.GroupVersionKind{backendGVK, extensionPolicyGVK} {
		list := &unstructured.UnstructuredList{}
		list.SetGroupVersionKind(gvk.GroupVersion().WithKind(gvk.Kind + "List"))
		if err := p.Client.List(ctx, list, client.MatchingLabels{exchangeManagedLabel: "true"}); err != nil {
			return err
		}
		for i := range list.Items {
			object := &list.Items[i]
			if !desired[types.NamespacedName{Namespace: object.GetNamespace(), Name: object.GetName()}] {
				if err := p.Client.Delete(ctx, object); err != nil && !apierrors.IsNotFound(err) {
					return err
				}
			}
		}
	}
	routes := &gatewayv1.HTTPRouteList{}
	if err := p.Client.List(ctx, routes, client.MatchingLabels{exchangeManagedLabel: "true"}); err != nil {
		return err
	}
	for i := range routes.Items {
		route := &routes.Items[i]
		if !desired[types.NamespacedName{Namespace: route.Namespace, Name: route.Name}] {
			if err := p.Client.Delete(ctx, route); err != nil && !apierrors.IsNotFound(err) {
				return err
			}
		}
	}
	grants := &unstructured.UnstructuredList{}
	grants.SetGroupVersionKind(referenceGrantGVK.GroupVersion().WithKind("ReferenceGrantList"))
	if err := p.Client.List(ctx, grants, client.MatchingLabels{exchangeManagedLabel: "true"}); err != nil {
		return err
	}
	for i := range grants.Items {
		grant := &grants.Items[i]
		if _, ok := state[grant.GetLabels()[exchangeSourceNSLabel]]; !ok {
			if err := p.Client.Delete(ctx, grant); err != nil && !apierrors.IsNotFound(err) {
				return err
			}
		}
	}
	return nil
}

func (p *ExchangeProjector) agentClientID(ctx context.Context, namespace, agent string) (string, error) {
	prefix := strings.TrimSpace(p.OIDCSecretPrefix)
	if prefix == "" {
		prefix = "kaos-oidc"
	}
	secret := &corev1.Secret{}
	name := security.CredentialSecretName(prefix, agent)
	if err := p.Client.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, secret); err != nil {
		return "", fmt.Errorf("reading Keycloak credentials for Agent %q: %w", agent, err)
	}
	clientID := secretValue(secret, credentialClientIDKey)
	if clientID == "" {
		return "", fmt.Errorf("Keycloak credential Secret %s/%s has no client_id", namespace, name)
	}
	return clientID, nil
}

func exchangeRouteName(serviceID string, origin exchangeOrigin) string {
	hash := sha256.Sum256([]byte(serviceID + "\x00" + origin.key()))
	return fmt.Sprintf("kaos-egress-%x", hash[:8])
}

func managedLabels(serviceID string) map[string]string {
	labels := map[string]string{"app.kubernetes.io/managed-by": "kaos-operator", exchangeManagedLabel: "true"}
	if serviceID != "" {
		labels[exchangeServiceIDLabel] = serviceID
	}
	return labels
}

func managedRouteLabels(serviceID string) map[string]string {
	labels := managedLabels(serviceID)
	labels[exchangeRouteLabel] = "true"
	return labels
}

func stringField(object map[string]any, field string) string {
	value, _ := object[field].(string)
	return strings.TrimSpace(value)
}

func objectSlice(value any) []map[string]any {
	items, _ := value.([]any)
	if direct, ok := value.([]map[string]any); ok {
		return direct
	}
	result := make([]map[string]any, 0, len(items))
	for _, item := range items {
		if object, ok := item.(map[string]any); ok {
			result = append(result, object)
		}
	}
	return result
}

func stringSlice(value any) []string {
	items, _ := value.([]any)
	if direct, ok := value.([]string); ok {
		return direct
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		if text, ok := item.(string); ok && strings.TrimSpace(text) != "" {
			result = append(result, text)
		}
	}
	return result
}

func uniqueSorted(values []string) []string {
	set := map[string]bool{}
	for _, value := range values {
		if value = strings.TrimSpace(value); value != "" {
			set[value] = true
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}
