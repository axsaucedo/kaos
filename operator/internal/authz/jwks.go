package authz

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"

	"k8s.io/client-go/rest"
)

// IssuerKeys is a discovered OIDC issuer and its signing keys.
type IssuerKeys struct {
	Issuer string
	JWKS   map[string]any
}

// DiscoverServiceAccountIssuer reads the API server's OIDC discovery document
// and JWKS using the operator's Kubernetes REST transport. HTTPClientFor applies
// the configured cluster CA and bearer credentials.
func DiscoverServiceAccountIssuer(ctx context.Context, cfg *rest.Config) (IssuerKeys, error) {
	httpClient, err := rest.HTTPClientFor(cfg)
	if err != nil {
		return IssuerKeys{}, fmt.Errorf("building Kubernetes OIDC client: %w", err)
	}
	discoveryURL := strings.TrimRight(cfg.Host, "/") + "/.well-known/openid-configuration"
	var discovery struct {
		Issuer  string `json:"issuer"`
		JWKSURI string `json:"jwks_uri"`
	}
	if err := fetchJSON(ctx, httpClient, discoveryURL, &discovery); err != nil {
		return IssuerKeys{}, fmt.Errorf("discovering Kubernetes ServiceAccount issuer: %w", err)
	}
	if strings.TrimSpace(discovery.Issuer) == "" {
		return IssuerKeys{}, fmt.Errorf("Kubernetes OIDC discovery returned an empty issuer")
	}
	jwksURL := strings.TrimSpace(discovery.JWKSURI)
	fallbackJWKSURL := strings.TrimRight(cfg.Host, "/") + "/openid/v1/jwks"
	if jwksURL == "" {
		jwksURL = fallbackJWKSURL
	} else if parsed, parseErr := url.Parse(jwksURL); parseErr != nil {
		jwksURL = fallbackJWKSURL
	} else {
		base, _ := url.Parse(strings.TrimRight(cfg.Host, "/") + "/")
		if !parsed.IsAbs() {
			jwksURL = base.ResolveReference(parsed).String()
		} else if parsed.Scheme != base.Scheme || parsed.Host != base.Host {
			// Never send the operator's API bearer token to a different origin.
			jwksURL = fallbackJWKSURL
		}
	}
	jwks, err := FetchJWKS(ctx, httpClient, jwksURL)
	if err != nil && jwksURL != fallbackJWKSURL {
		jwks, err = FetchJWKS(ctx, httpClient, fallbackJWKSURL)
	}
	if err != nil {
		return IssuerKeys{}, err
	}
	return IssuerKeys{Issuer: strings.TrimSpace(discovery.Issuer), JWKS: jwks}, nil
}

func fetchJSON(ctx context.Context, client *http.Client, endpoint string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return err
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status %s", resp.Status)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// FetchJWKS retrieves the JSON Web Key Set published at url and returns it as a
// generic document suitable for injection at `data.kaos.jwks`. The returned
// value is the JWKS object verbatim (typically `{"keys": [...]}`), which the
// policy passes to `io.jwt.decode_verify` as the verification certificate set.
func FetchJWKS(ctx context.Context, client *http.Client, url string) (map[string]any, error) {
	if client == nil {
		client = http.DefaultClient
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("building JWKS request: %w", err)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetching JWKS from %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fetching JWKS from %s: unexpected status %s", url, resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading JWKS from %s: %w", url, err)
	}
	var jwks map[string]any
	if err := json.Unmarshal(body, &jwks); err != nil {
		return nil, fmt.Errorf("parsing JWKS from %s: %w", url, err)
	}
	return jwks, nil
}
