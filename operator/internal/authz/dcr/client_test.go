package dcr

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

func TestClientRegistrationLifecycle(t *testing.T) {
	var server *httptest.Server
	registered := false
	deleted := false
	updated := false
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/.well-known/openid-configuration":
			writeJSON(t, w, http.StatusOK, map[string]string{
				"issuer":                server.URL,
				"registration_endpoint": server.URL + "/register",
			})
		case r.URL.Path == "/register" && r.Method == http.MethodPost:
			if r.Header.Get("Authorization") != "Bearer bootstrap" {
				t.Fatalf("registration authorization = %q", r.Header.Get("Authorization"))
			}
			var request RegistrationRequest
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Fatalf("decode registration: %v", err)
			}
			want := AgentRegistrationRequest("kaos://agent/demo/researcher")
			if !reflect.DeepEqual(request, want) {
				t.Fatalf("registration request = %+v, want %+v", request, want)
			}
			registered = true
			writeJSON(t, w, http.StatusCreated, registrationResponse(server.URL))
		case r.URL.Path == "/register/client-1" && r.Method == http.MethodGet:
			if r.Header.Get("Authorization") != "Bearer manage-1" {
				t.Fatalf("management authorization = %q", r.Header.Get("Authorization"))
			}
			if !registered || deleted {
				http.NotFound(w, r)
				return
			}
			writeJSON(t, w, http.StatusOK, map[string]any{
				"client_id": "client-1", "client_name": "kaos://agent/demo/researcher",
				"grant_types":                []string{"client_credentials"},
				"token_endpoint_auth_method": "client_secret_basic",
			})
		case r.URL.Path == "/register/client-1" && r.Method == http.MethodDelete:
			if r.Header.Get("Authorization") != "Bearer manage-1" {
				t.Fatalf("delete authorization = %q", r.Header.Get("Authorization"))
			}
			if deleted {
				http.NotFound(w, r)
				return
			}
			deleted = true
			w.WriteHeader(http.StatusNoContent)
		case r.URL.Path == "/register/client-1" && r.Method == http.MethodPut:
			if r.Header.Get("Authorization") != "Bearer manage-1" {
				t.Fatalf("update authorization = %q", r.Header.Get("Authorization"))
			}
			var request map[string]any
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Fatalf("decode update: %v", err)
			}
			if request["client_id"] != "client-1" || request["client_name"] != "kaos://agent/demo/researcher" {
				t.Fatalf("update request = %+v", request)
			}
			updated = true
			writeJSON(t, w, http.StatusOK, registrationResponse(server.URL))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	client := &Client{Issuer: server.URL, InitialAccessToken: "bootstrap", HTTPClient: server.Client()}
	registration, err := client.Register(context.Background(), AgentRegistrationRequest("kaos://agent/demo/researcher"))
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	ref := referenceFromRegistration(registration)
	got, err := client.Get(context.Background(), ref)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.ClientID != "client-1" || got.RegistrationClientURI != server.URL+"/register/client-1" || got.RegistrationAccessToken != "manage-1" {
		t.Fatalf("get registration = %+v", got)
	}
	if _, err := client.Update(context.Background(), ref, AgentRegistrationRequest("kaos://agent/demo/researcher")); err != nil {
		t.Fatalf("update: %v", err)
	}
	if !updated {
		t.Fatal("client was not updated")
	}
	if err := client.Delete(context.Background(), ref); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if !deleted {
		t.Fatal("client was not deleted")
	}
	if err := client.Delete(context.Background(), ref); err != nil {
		t.Fatalf("second delete must tolerate an absent client: %v", err)
	}
}

func TestClientRejectsCrossOriginRegistrationURI(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/.well-known/openid-configuration":
			writeJSON(t, w, http.StatusOK, map[string]string{"registration_endpoint": "http://provider.example/register"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	client := &Client{Issuer: server.URL, HTTPClient: server.Client()}
	err := client.Delete(context.Background(), Reference{ClientID: "client-1", RegistrationClientURI: "http://attacker.example/client-1", RegistrationAccessToken: "manage-1"})
	if err == nil {
		t.Fatal("expected cross-origin registration_client_uri to be rejected")
	}
}

func registrationResponse(baseURL string) Registration {
	return Registration{
		ClientID: "client-1", ClientSecret: "secret-1",
		RegistrationAccessToken: "manage-1", RegistrationClientURI: baseURL + "/register/client-1",
		ClientName: "kaos://agent/demo/researcher", GrantTypes: []string{"client_credentials"},
		TokenEndpointAuthMethod: "client_secret_basic",
	}
}

func referenceFromRegistration(registration Registration) Reference {
	return Reference{ClientID: registration.ClientID, RegistrationClientURI: registration.RegistrationClientURI, RegistrationAccessToken: registration.RegistrationAccessToken}
}

func writeJSON(t *testing.T, w http.ResponseWriter, status int, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatalf("encode response: %v", err)
	}
}
