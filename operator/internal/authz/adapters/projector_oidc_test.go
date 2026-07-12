package adapters

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/authz/dcr"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

func TestOIDCProjectorLifecycle(t *testing.T) {
	provider := newFakeOIDCProvider(t)
	defer provider.server.Close()

	scheme := newTestScheme(t)
	agent := &kaosv1alpha1.Agent{
		ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher", UID: types.UID("agent-uid")},
		Spec:       kaosv1alpha1.AgentSpec{ModelAPI: "gpt"},
	}
	kubeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(agent).Build()
	projector := &OIDCProjector{
		Client: kubeClient, Scheme: scheme, SecretPrefix: "kaos-oidc", Prune: true,
		DCR: &dcr.Client{Issuer: provider.server.URL, InitialAccessToken: "bootstrap", HTTPClient: provider.server.Client()},
	}
	desired := projection.Project([]projection.Resource{resourceFromAgent(agent)})

	t.Run("registers and stores credentials and management reference", func(t *testing.T) {
		if err := projector.Apply(context.Background(), desired); err != nil {
			t.Fatalf("apply: %v", err)
		}
		if provider.registered != 1 {
			t.Fatalf("registrations = %d, want 1", provider.registered)
		}
		secret := &corev1.Secret{}
		key := types.NamespacedName{Namespace: "demo", Name: "kaos-oidc-researcher"}
		if err := kubeClient.Get(context.Background(), key, secret); err != nil {
			t.Fatalf("get Secret: %v", err)
		}
		wantValues := map[string]string{
			credentialClientIDKey:      "client-1",
			credentialClientSecretKey:  "secret-1",
			registrationClientURIKey:   provider.server.URL + "/register/client-1",
			registrationAccessTokenKey: "manage-1",
		}
		for key, want := range wantValues {
			if got := secretValue(secret, key); got != want {
				t.Errorf("Secret %s = %q, want %q", key, got, want)
			}
		}
		if secret.Annotations[oidcAgentExternalIDAnnotation] != "kaos://agent/demo/researcher" {
			t.Fatalf("external ID annotation = %q", secret.Annotations[oidcAgentExternalIDAnnotation])
		}
		if len(secret.OwnerReferences) != 1 || secret.OwnerReferences[0].Name != agent.Name || secret.OwnerReferences[0].Controller == nil || !*secret.OwnerReferences[0].Controller {
			t.Fatalf("unexpected owner references: %+v", secret.OwnerReferences)
		}
	})

	t.Run("second apply reuses provider client", func(t *testing.T) {
		if err := projector.Apply(context.Background(), desired); err != nil {
			t.Fatalf("second apply: %v", err)
		}
		if provider.registered != 1 {
			t.Fatalf("second apply registered another client: %d", provider.registered)
		}
		if provider.got != 1 {
			t.Fatalf("RFC 7592 GET calls = %d, want 1", provider.got)
		}
	})

	t.Run("prune deletes provider client before Secret", func(t *testing.T) {
		if err := projector.Apply(context.Background(), projection.DesiredState{}); err != nil {
			t.Fatalf("prune apply: %v", err)
		}
		if provider.deleted != 1 {
			t.Fatalf("deletions = %d, want 1", provider.deleted)
		}
		secret := &corev1.Secret{}
		err := kubeClient.Get(context.Background(), types.NamespacedName{Namespace: "demo", Name: "kaos-oidc-researcher"}, secret)
		if !apierrors.IsNotFound(err) {
			t.Fatalf("credential Secret still exists: %v", err)
		}
	})
}

type fakeOIDCProvider struct {
	t          *testing.T
	server     *httptest.Server
	registered int
	got        int
	deleted    int
	clients    map[string]bool
}

func newFakeOIDCProvider(t *testing.T) *fakeOIDCProvider {
	t.Helper()
	provider := &fakeOIDCProvider{t: t, clients: map[string]bool{}}
	provider.server = httptest.NewServer(http.HandlerFunc(provider.serveHTTP))
	return provider
}

func (p *fakeOIDCProvider) serveHTTP(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.URL.Path == "/.well-known/openid-configuration":
		p.writeJSON(w, http.StatusOK, map[string]string{
			"issuer": p.server.URL, "registration_endpoint": p.server.URL + "/register",
		})
	case r.URL.Path == "/register" && r.Method == http.MethodPost:
		if r.Header.Get("Authorization") != "Bearer bootstrap" {
			p.t.Errorf("registration authorization = %q", r.Header.Get("Authorization"))
		}
		var request dcr.RegistrationRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			p.t.Errorf("decode registration: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if request.ClientName != "kaos://agent/demo/researcher" || len(request.GrantTypes) != 1 || request.GrantTypes[0] != "client_credentials" || request.TokenEndpointAuthMethod != "client_secret_basic" {
			p.t.Errorf("unexpected registration request: %+v", request)
		}
		p.registered++
		id := fmt.Sprintf("client-%d", p.registered)
		p.clients[id] = true
		p.writeJSON(w, http.StatusCreated, dcr.Registration{
			ClientID: id, ClientSecret: fmt.Sprintf("secret-%d", p.registered),
			RegistrationAccessToken: fmt.Sprintf("manage-%d", p.registered),
			RegistrationClientURI:   p.server.URL + "/register/" + id,
		})
	case r.Method == http.MethodGet && p.clientID(r) != "":
		id := p.clientID(r)
		if !p.authorized(r, id) || !p.clients[id] {
			http.NotFound(w, r)
			return
		}
		p.got++
		p.writeJSON(w, http.StatusOK, map[string]string{"client_id": id})
	case r.Method == http.MethodDelete && p.clientID(r) != "":
		id := p.clientID(r)
		if !p.authorized(r, id) || !p.clients[id] {
			http.NotFound(w, r)
			return
		}
		delete(p.clients, id)
		p.deleted++
		w.WriteHeader(http.StatusNoContent)
	default:
		http.NotFound(w, r)
	}
}

func (p *fakeOIDCProvider) clientID(r *http.Request) string {
	const prefix = "/register/"
	if len(r.URL.Path) <= len(prefix) || r.URL.Path[:len(prefix)] != prefix {
		return ""
	}
	return r.URL.Path[len(prefix):]
}

func (p *fakeOIDCProvider) authorized(r *http.Request, id string) bool {
	return r.Header.Get("Authorization") == "Bearer manage-"+id[len("client-"):]
}

func (p *fakeOIDCProvider) writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		p.t.Errorf("encode response: %v", err)
	}
}
