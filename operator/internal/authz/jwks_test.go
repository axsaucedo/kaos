package authz

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
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

func TestFetchJWKSErrorsOnNonOK(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	if _, err := FetchJWKS(context.Background(), nil, srv.URL); err == nil {
		t.Fatal("expected error on non-200 response")
	}
}
