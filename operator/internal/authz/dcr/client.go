// Package dcr implements the RFC 7591 and RFC 7592 operations used to manage
// one OAuth client per KAOS agent.
package dcr

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"

	"github.com/axsaucedo/kaos/operator/internal/authz"
)

// RegistrationRequest is the OAuth client metadata controlled by KAOS.
type RegistrationRequest struct {
	ClientName              string   `json:"client_name"`
	GrantTypes              []string `json:"grant_types"`
	TokenEndpointAuthMethod string   `json:"token_endpoint_auth_method"`
}

// AgentRegistrationRequest returns the fixed client-credentials metadata used
// for an agent registration.
func AgentRegistrationRequest(clientName string) RegistrationRequest {
	return RegistrationRequest{
		ClientName:              clientName,
		GrantTypes:              []string{"client_credentials"},
		TokenEndpointAuthMethod: "client_secret_basic",
	}
}

// Registration contains credentials plus the RFC 7592 management reference.
type Registration struct {
	ClientID                string   `json:"client_id"`
	ClientSecret            string   `json:"client_secret"`
	RegistrationAccessToken string   `json:"registration_access_token"`
	RegistrationClientURI   string   `json:"registration_client_uri"`
	ClientName              string   `json:"client_name,omitempty"`
	GrantTypes              []string `json:"grant_types,omitempty"`
	TokenEndpointAuthMethod string   `json:"token_endpoint_auth_method,omitempty"`
}

// Reference is the persistent RFC 7592 handle required to manage a client.
type Reference struct {
	ClientID                string
	RegistrationClientURI   string
	RegistrationAccessToken string
}

// Client talks to the provider selected by Issuer.
type Client struct {
	Issuer             string
	InitialAccessToken string
	HTTPClient         *http.Client
}

// Register creates a client through the provider's discovered RFC 7591 endpoint.
func (c *Client) Register(ctx context.Context, request RegistrationRequest) (Registration, error) {
	endpoint, err := authz.DiscoverRegistrationEndpoint(ctx, c.httpClient(), c.Issuer)
	if err != nil {
		return Registration{}, err
	}
	if strings.TrimSpace(c.InitialAccessToken) == "" {
		return Registration{}, fmt.Errorf("initial access token is empty")
	}
	var registration Registration
	if err := c.doJSON(ctx, http.MethodPost, endpoint, c.InitialAccessToken, request, &registration, http.StatusCreated, http.StatusOK); err != nil {
		return Registration{}, fmt.Errorf("registering OAuth client: %w", err)
	}
	if err := validateRegistration(registration); err != nil {
		return Registration{}, err
	}
	if _, err := c.managementEndpoint(ctx, registration.RegistrationClientURI); err != nil {
		return Registration{}, err
	}
	return registration, nil
}

// Get reads the current client metadata through RFC 7592.
func (c *Client) Get(ctx context.Context, ref Reference) (Registration, error) {
	if err := validateReference(ref); err != nil {
		return Registration{}, err
	}
	endpoint, err := c.managementEndpoint(ctx, ref.RegistrationClientURI)
	if err != nil {
		return Registration{}, err
	}
	var registration Registration
	if err := c.doJSON(ctx, http.MethodGet, endpoint, ref.RegistrationAccessToken, nil, &registration, http.StatusOK); err != nil {
		return Registration{}, fmt.Errorf("reading OAuth client: %w", err)
	}
	if registration.ClientID == "" {
		registration.ClientID = ref.ClientID
	}
	if registration.RegistrationClientURI == "" {
		registration.RegistrationClientURI = ref.RegistrationClientURI
	}
	if registration.RegistrationAccessToken == "" {
		registration.RegistrationAccessToken = ref.RegistrationAccessToken
	}
	return registration, nil
}

// Update replaces the client metadata through RFC 7592.
func (c *Client) Update(ctx context.Context, ref Reference, request RegistrationRequest) (Registration, error) {
	if err := validateReference(ref); err != nil {
		return Registration{}, err
	}
	endpoint, err := c.managementEndpoint(ctx, ref.RegistrationClientURI)
	if err != nil {
		return Registration{}, err
	}
	payload := struct {
		RegistrationRequest
		ClientID string `json:"client_id"`
	}{RegistrationRequest: request, ClientID: ref.ClientID}
	var registration Registration
	if err := c.doJSON(ctx, http.MethodPut, endpoint, ref.RegistrationAccessToken, payload, &registration, http.StatusOK); err != nil {
		return Registration{}, fmt.Errorf("updating OAuth client: %w", err)
	}
	if registration.ClientID == "" {
		registration.ClientID = ref.ClientID
	}
	if registration.RegistrationClientURI == "" {
		registration.RegistrationClientURI = ref.RegistrationClientURI
	}
	if registration.RegistrationAccessToken == "" {
		registration.RegistrationAccessToken = ref.RegistrationAccessToken
	}
	return registration, nil
}

// Delete removes a client through RFC 7592. An already-absent client is success.
func (c *Client) Delete(ctx context.Context, ref Reference) error {
	if err := validateReference(ref); err != nil {
		return err
	}
	endpoint, err := c.managementEndpoint(ctx, ref.RegistrationClientURI)
	if err != nil {
		return err
	}
	err = c.doJSON(ctx, http.MethodDelete, endpoint, ref.RegistrationAccessToken, nil, nil, http.StatusNoContent, http.StatusOK)
	if IsNotFound(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("deleting OAuth client: %w", err)
	}
	return nil
}

// HTTPError reports a non-success provider response without exposing its body.
type HTTPError struct {
	StatusCode int
	Status     string
}

func (e *HTTPError) Error() string { return "unexpected status " + e.Status }

// IsNotFound reports whether an RFC 7592 operation found no client.
func IsNotFound(err error) bool {
	var httpErr *HTTPError
	return errors.As(err, &httpErr) && httpErr.StatusCode == http.StatusNotFound
}

func (c *Client) managementEndpoint(ctx context.Context, rawURI string) (string, error) {
	registrationEndpoint, err := authz.DiscoverRegistrationEndpoint(ctx, c.httpClient(), c.Issuer)
	if err != nil {
		return "", err
	}
	registrationURL, err := parseHTTPURL(registrationEndpoint)
	if err != nil {
		return "", fmt.Errorf("invalid registration_endpoint: %w", err)
	}
	managementURL, err := parseHTTPURL(rawURI)
	if err != nil {
		return "", fmt.Errorf("invalid registration_client_uri: %w", err)
	}
	if registrationURL.Scheme != managementURL.Scheme || registrationURL.Host != managementURL.Host {
		return "", fmt.Errorf("registration_client_uri origin does not match registration_endpoint")
	}
	return managementURL.String(), nil
}

func parseHTTPURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return nil, fmt.Errorf("must be an absolute HTTP(S) URL")
	}
	return parsed, nil
}

func validateReference(ref Reference) error {
	if strings.TrimSpace(ref.ClientID) == "" || strings.TrimSpace(ref.RegistrationClientURI) == "" || strings.TrimSpace(ref.RegistrationAccessToken) == "" {
		return fmt.Errorf("incomplete OAuth client registration reference")
	}
	return nil
}

func validateRegistration(registration Registration) error {
	if strings.TrimSpace(registration.ClientSecret) == "" {
		return fmt.Errorf("provider returned an incomplete OAuth client registration")
	}
	return validateReference(Reference{
		ClientID:                registration.ClientID,
		RegistrationClientURI:   registration.RegistrationClientURI,
		RegistrationAccessToken: registration.RegistrationAccessToken,
	})
}

func (c *Client) doJSON(ctx context.Context, method, endpoint, token string, payload, out any, expected ...int) error {
	var body io.Reader
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		body = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")
	resp, err := c.httpClient().Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	for _, status := range expected {
		if resp.StatusCode == status {
			if out == nil || resp.StatusCode == http.StatusNoContent {
				_, _ = io.Copy(io.Discard, resp.Body)
				return nil
			}
			return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(out)
		}
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	return &HTTPError{StatusCode: resp.StatusCode, Status: resp.Status}
}

func (c *Client) httpClient() *http.Client {
	if c.HTTPClient != nil {
		return c.HTTPClient
	}
	return http.DefaultClient
}
