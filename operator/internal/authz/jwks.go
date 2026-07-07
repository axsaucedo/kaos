package authz

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

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
