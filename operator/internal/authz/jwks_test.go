package authz

import (
	"context"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"testing"

	"k8s.io/client-go/rest"
)

func TestFetchJWKSParsesKeySet(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"keys":[{"kty":"RSA","kid":"k1"}]}`))
	}))
	defer srv.Close()

	jwks, err := FetchJWKS(context.Background(), nil, srv.URL)
	if err != nil {
		t.Fatalf("FetchJWKS: %v", err)
	}
	keys, ok := jwks["keys"].([]any)
	if !ok || len(keys) != 1 {
		t.Fatalf("unexpected keys: %v", jwks)
	}
}

func TestDiscoverServiceAccountIssuerUsesKubernetesTLSAndCredentials(t *testing.T) {
	var server *httptest.Server
	server = httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer operator-token" {
			t.Errorf("authorization header = %q", r.Header.Get("Authorization"))
		}
		switch r.URL.Path {
		case "/.well-known/openid-configuration":
			_, _ = w.Write([]byte(`{"issuer":"https://kubernetes.default.svc","jwks_uri":"` + server.URL + `/openid/v1/jwks"}`))
		case "/openid/v1/jwks":
			_, _ = w.Write([]byte(`{"keys":[{"kty":"RSA","kid":"sa-key"}]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	caData := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: server.Certificate().Raw})
	got, err := DiscoverServiceAccountIssuer(context.Background(), &rest.Config{
		Host:        server.URL,
		BearerToken: "operator-token",
		TLSClientConfig: rest.TLSClientConfig{
			CAData: caData,
		},
	})
	if err != nil {
		t.Fatalf("DiscoverServiceAccountIssuer: %v", err)
	}
	if got.Issuer != "https://kubernetes.default.svc" {
		t.Fatalf("issuer = %q", got.Issuer)
	}
	keys := got.JWKS["keys"].([]any)
	if keys[0].(map[string]any)["kid"] != "sa-key" {
		t.Fatalf("JWKS = %#v", got.JWKS)
	}
}

func TestDiscoverServiceAccountIssuerKeepsCredentialsOnAPIServerOrigin(t *testing.T) {
	externalRequests := 0
	external := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		externalRequests++
	}))
	defer external.Close()

	var server *httptest.Server
	server = httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/.well-known/openid-configuration":
			_, _ = w.Write([]byte(`{"issuer":"https://kubernetes.default.svc","jwks_uri":"` + external.URL + `/jwks"}`))
		case "/openid/v1/jwks":
			_, _ = w.Write([]byte(`{"keys":[{"kid":"internal"}]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	caData := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: server.Certificate().Raw})
	if _, err := DiscoverServiceAccountIssuer(context.Background(), &rest.Config{
		Host: server.URL, BearerToken: "operator-token",
		TLSClientConfig: rest.TLSClientConfig{CAData: caData},
	}); err != nil {
		t.Fatalf("DiscoverServiceAccountIssuer: %v", err)
	}
	if externalRequests != 0 {
		t.Fatalf("operator credentials were sent to an external JWKS origin")
	}
}

func TestFetchJWKSErrorsOnNonOK(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	if _, err := FetchJWKS(context.Background(), nil, srv.URL); err == nil {
		t.Fatal("expected error on non-200 response")
	}
}
